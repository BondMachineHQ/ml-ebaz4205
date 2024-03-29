from tensorflow.keras.utils import to_categorical
from sklearn.datasets import fetch_openml
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import LabelEncoder, StandardScaler
from tensorflow.keras.models import Sequential, load_model, save_model
from tensorflow.keras.layers import Dense, Activation, BatchNormalization
from tensorflow.keras.optimizers import Adam, Adagrad
from tensorflow.keras.regularizers import l1
import numpy as np
import os
import tensorflow.compat.v1 as tf
import pandas as pd
tf.disable_v2_behavior()
import ssl
import sys
import argparse
from sklearn.metrics import accuracy_score
import hls4ml
import matplotlib.pyplot as plt
import json
from os.path import exists
import networkx as nx
import pylab
from networkx.drawing.nx_agraph import graphviz_layout
import subprocess
import tensorflow_model_optimization as tfmot
from tensorflow_model_optimization.sparsity.keras import PolynomialDecay
from qkeras import *

class bcolors:
    WHITE = '\033[97m'
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKCYAN = '\033[96m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'

class Trainer:

    def __init__(self, fpga_part_number, fpga_board_name, nn_model_type):
        
        self.nn_model_type = nn_model_type
        self.fpga_part_number = fpga_part_number
        self.fpga_board_name = fpga_board_name
        self.available_datasets = [
            "mnist_784", 
            "CIFAR_10", 
            "banknote-authentication",
            "Fashion-MNIST",
            "hls4ml_lhc_jets_hlf",
            "shuttle-landing-control",
            "climate-model-simulation-crashes",
            "monks-problems-2",
            "diabetes",
            "pc4",
            "madelon",
            "scene", 
            "PhishingWebsites",
            "optdigits",
            "higgs",
            "dna"]
        self.dataset = None
        self.vivado_path = '/home/ubuntu/Vivado/2019.2/bin:'
        self.seed = 0
        self.le = LabelEncoder()
        self.X_train_val = None
        self.X_test = None
        self.y_train_val = None
        self.y_test = None
        self.model = None
        self.hls_model = None
        self.classes_len = 0
        self.train_size = 0
        self.network_spec = None
        self.hls4ml_supported_boards = [
            {
                "name": "pynq-z2",
                "part": "xc7z020clg400-1"
            },
            {
                "name": "zcu102",
                "part": "xczu9eg-ffvb1156-2-e"
            },
            {
                "name": "alveo-u50",
                "part": "xcu50-fsvh2104-2-e"
            },
            {
                "name": "alveo-u250",
                "part": "xcu250-figd2104-2L-e"
            },
            {
                "name": "alveo-u200",
                "part": "xcu200-fsgd2104-2-e"
            },
            {
                "name": "alveo-u280",
                "part": "xcu280-fsvh2892-2L-e"
            }
        ]
        self.neural_networks_params = []
        self.pruning = False

    def initialize(self) -> None:
        
        ssl._create_default_https_context = ssl._create_unverified_context
        np.random.seed(self.seed)
        #tf.random.set_random_seed(self.seed)
        os.environ['PATH'] = self.vivado_path + os.environ['PATH']

    def setup_data(self, dataset) -> None:

        if dataset not in self.available_datasets:
            raise Exception("Dataset not available. Availables are: ", self.available_datasets)

        # Create the dataset dir if not exists
        if not os.path.exists("datasets"):
            os.makedirs("datasets")

        self.dataset = dataset
        file_exists = os.path.exists("datasets/"+dataset+'_X_train_val.npy')
        user_reply = ""
        if file_exists:
            question = bcolors.WARNING + " # QUESTION: Dataset already exists, force re-download? (y/n) "+bcolors.WHITE
            user_reply = input(question)
        else:
            user_reply = "y"
        
        if user_reply == "y":
            data = fetch_openml(dataset)
            x_data, y_data = data['data'], data['target']
            
            pd.DataFrame(x_data).to_csv("datasets/"+dataset+'_raw_x_data.csv', index=False)
            pd.DataFrame(y_data).to_csv("datasets/"+dataset+'_raw_y_data.csv', index=False)

            y = self.le.fit_transform(y_data)
            unique = np.unique(y)
            y = to_categorical(y, len(unique))

            self.X_train_val, self.X_test, self.y_train_val, self.y_test = train_test_split(x_data, y, test_size=0.2, random_state=42)
            
            scaler = StandardScaler()
            self.X_train_val = scaler.fit_transform(self.X_train_val)
            self.X_test = scaler.transform(self.X_test)
            self.classes = self.le.classes_

            
            np.save("datasets/"+dataset+'_X_train_val.npy', self.X_train_val)
            np.save("datasets/"+dataset+'_X_test.npy', self.X_test)
            np.save("datasets/"+dataset+'_y_train_val.npy', self.y_train_val)
            np.save("datasets/"+dataset+'_y_test.npy', self.y_test)
            np.save("datasets/"+dataset+'_classes.npy', self.le.classes_)

        else:
            print(bcolors.OKGREEN + " # INFO: Loading dataset", self.dataset+bcolors.WHITE)
            self.X_train_val = np.load("datasets/"+dataset+'_X_train_val.npy')
            self.X_test = np.load("datasets/"+dataset+'_X_test.npy')
            self.y_train_val = np.load("datasets/"+dataset+'_y_train_val.npy')
            self.y_test = np.load("datasets/"+dataset+'_y_test.npy')
            self.classes = np.load("datasets/"+dataset+'_classes.npy', allow_pickle=True)
            

    def parse_network_specifics(self):
        
        try:
            f = open('specifics.json')
            self.network_spec = json.load(f)
        except:
            return

    def build_model(self):
        if self.nn_model_type == "MLP":

            self.model = Sequential()

            self.parse_network_specifics()

            if self.network_spec == None:
                for i in range(0, 24, 3):
                    self.model.add(Dense(i, input_shape=(self.X_train_val.shape[1],)))
                for i in reversed(range(0, 24, 3)):
                    self.model.add(Dense(i, input_shape=(self.X_train_val.shape[1],)))
                # self.model.add(Dense(10, input_shape=(self.X_train_val.shape[1],)))
                # self.model.add(Dense(15, input_shape=(self.X_train_val.shape[1],)))
                # self.model.add(Dense(20, input_shape=(self.X_train_val.shape[1],)))
                # self.model.add(Dense(15, input_shape=(self.X_train_val.shape[1],)))
                # self.model.add(Dense(10, input_shape=(self.X_train_val.shape[1],)))
                #for i in range(1, 2):
                #    self.model.add(Dense(i, input_shape=(self.X_train_val.shape[1],)))
                # self.model.add(Activation(activation='relu'))
                # self.model.add(Dense(8, name='fc2', kernel_initializer='lecun_uniform', kernel_regularizer=l1(0.0001)))
                # self.model.add(Activation(activation='relu'))
                opt = Adam(lr=0.0001)
            else:
                arch = self.network_spec["network"]["arch"]
                for i in range(0, len(arch)):
                    layer_name = self.network_spec["network"]["arch"][i]["layer_name"]
                    activation_function = self.network_spec["network"]["arch"][i]["activation_function"]
                    neurons = self.network_spec["network"]["arch"][i]["neurons"]
                    if i == 0:
                        self.model.add(Dense(neurons, activation=activation_function, input_shape=(self.X_train_val.shape[1],), kernel_regularizer=l1(0.0001)))
                    else:
                        self.model.add(Dense(neurons, activation=activation_function, name=layer_name, kernel_regularizer=l1(0.0001)))
                    #self.model.add(Activation(activation=activation_function))

                if  self.network_spec["network"]["training"]["optimizer"] == "Adam":
                    opt = Adam(lr=0.0001)
                elif self.network_spec["network"]["training"]["optimizer"] == "Adagrad":
                    opt = Adagrad(lr=0.0001)
                else:
                    opt = Adam(lr=0.0001)
                # handle more opt
                
                self.pruning = True if self.network_spec["network"]["training"]["pruning"] == "true" else False
                
            self.model.add(Dense(self.classes_len, activation='softmax'))
            self.model.compile(optimizer=opt, loss=['categorical_crossentropy'], metrics=['accuracy'])

        # WIP: to handle more model type

    def get_json_model(self):

        import json
        layers = self.model.layers
        to_export = {}

        for i in range(0 , len(layers)):
            layer_info = {}
            layer_weights = layers[i].get_weights()[0].tolist()
            bias = layers[i].get_weights()[1]

            flat_layer_weigth = [item for sublist in layer_weights for item in sublist]

            layer_info["weigths"] = flat_layer_weigth
            layer_info["bias"] = bias.tolist()
            
            name = ""
            try:
                name = layers[i].activation.__name__
            except Exception as e:
                name = str(layers[i].activation)

            layer_info["act_func"] = name
            to_export["layer_"+str(i)] = layer_info

        with open('models/'+self.dataset+'/model.json', 'w') as fp:
            json.dump(to_export, fp)

    def dump_json_for_bondmachine(self):
        import json

        layers = self.model.layers
        weights = self.model.weights

        to_dump = {}

        weights = []
        nodes = []

        weights_value = []

        # save weigths
        for i in range(0 , len(layers)):

            layer_weights = layers[i].get_weights()

            for m in range(0, len(layer_weights)):
                for w in range(0, len(layer_weights[m])):
                    try:
                        for v in range(0, len(layer_weights[m][w])):
                            
                            if float(layer_weights[m][w][v]) == 0:
                                continue
                            
                            weights_value.append(float(layer_weights[m][w][v]))

                            weight_info = {
                                    "Layer": i+1,
                                    "PosCurrLayer": v,
                                    "PosPrevLayer": w,
                                    "Value": float(layer_weights[m][w][v])
                                }
                            self.neural_networks_params.append(float(layer_weights[m][w][v]))
                            weights.append(weight_info)
                    except:
                        continue

            if i == 0:
                for units in range(0, layers[i].units):
                    weights_l0 = layers[i].get_weights()[0]

                    for w in range(0, len(weights_l0)):
                        node_info = {
                            "Layer": 0,
                            "Pos": w,
                            "Type": "input",
                            "Bias": 0
                        }
                        self.neural_networks_params.append(0)
                        nodes.append(node_info)
                    break
           

            for units in range(0, layers[i].units):
                if i == len(layers) - 1:
                    bias = layers[i].get_weights()[1]
                    node_info = {
                        "Layer": i+1,
                        "Pos": units,
                        "Type": "summation",
                        "Bias": bias.tolist()[units]
                    }
                    nodes.append(node_info)
                    self.neural_networks_params.append(float(node_info["Bias"]))
                    weights_value.append(node_info["Bias"])
                else:
                    name = ""
                    try:
                        name = layers[i].activation.__name__
                    except Exception as e:
                        name = str(layers[i].activation)
                        
                    bias = layers[i].get_weights()[1]
                    node_info = {
                        "Layer": i+1,
                        "Pos": units,
                        "Type": name,
                        "Bias": bias.tolist()[units]
                    }
                    nodes.append(node_info)
                    self.neural_networks_params.append(float(node_info["Bias"]))
                    weights_value.append(node_info["Bias"])

            if i == len(layers) - 1:
                for l in range(0, len(layer_weights[0][0])):
                    node_info = {
                        "Layer": i+2,
                        "Pos": l,
                        "Type": "softmax",
                        "Bias": 0
                    }
                    nodes.append(node_info)


                layer_weights = layers[i-2].get_weights()

                for k in range(0, layers[i].units):
                    for l in range(0, layers[i].units):
                        weight_info = {
                                        "Layer": i+2,
                                        "PosCurrLayer": k,
                                        "PosPrevLayer": l,
                                        "Value": 1
                                    }
                        self.neural_networks_params.append(float(1))
                        weights.append(weight_info)


            if i == len(layers) - 1:

                layer_weights = layers[i].get_weights()

                for l in range(0, len(layer_weights[0][0])):
                    node_info = {
                        "Layer": i+3,
                        "Pos": l,
                        "Type": "output",
                        "Bias": 0
                    }
                    nodes.append(node_info)

                    weight_info = {
                                    "Layer": i+3,
                                    "PosCurrLayer": l,
                                    "PosPrevLayer": l,
                                    "Value": 1
                                }
                    print(weight_info)
                    weights.append(weight_info)

        to_dump["Nodes"] = nodes
        to_dump["Weights"] = weights

        with open('models/'+self.dataset+'/modelBM.json', 'w') as fp:
            print(" *** dump model")
            json.dump(to_dump, fp)

    def build_graph(self):

        plt.subplots(num=None, figsize=(200, 200), dpi=80, facecolor='w', edgecolor='k')
        G = nx.DiGraph()

        layers = self.model.layers
        weights = self.model.weights

        layer_index = 0
        layers_hist = []
        edge_list = []
        pos = {}

        max_layer_size = 0
        for layer in layers:
            layer_units = layer.units
            if layer_units > max_layer_size:
                max_layer_size = layer_units

        positions = []
        for k in range(0, int(max_layer_size)*2):
            positions.append(k)
            if k > 0:
                positions.append(-k)

        last_pos_used = positions[int(len(positions)/2)]
        inc_dex = 0

        for layer in layers:
            layer_weights = layer.get_weights()[0]
            bias = layer.get_weights()[1]
            layer_units = layer.units

            if layer_index == 0:
                for o in range(0, len(bias)):
                    for k in range(0, len(layer_weights)):
                        edge_list.append((str(layer_index-1)+"_"+str(k), str(o)+"_"+str(layer_index)))
                        pos[str(layer_index-1)+"_"+str(k)] = (layer_index-1, positions[k])
            else:   
                for m in range(0, layers_hist[layer_index-1]):
                    node_name = str(m)+"_"+str(layer_index-1)
                    pos[node_name] = (layer_index-1,positions[m])
                    
                    for l in range(0, layer_units):
                        edge_list.append((node_name, str(l)+"_"+str(layer_index)))
                        pos[str(l)+"_"+str(layer_index)] = (layer_index,positions[l])

            layer_index = layer_index + 1
            layers_hist.append(layer_units)
        
        G.add_edges_from(edge_list)
        nx.draw(
            G,
            pos = pos, # position of point
            node_color ='blue', # vertex color
            edge_color ='green', # edge color
            with_labels = True, # Display vertex labels
            font_size =8, # text size
            node_size =750, # vertex size
            font_color = "white"
        )
    
        plt.show()

    def exec_train(self):
        file_exists = os.path.exists('models/'+self.dataset+'_KERAS_model.h5')
        user_reply = ""
        if file_exists:
            question = bcolors.WARNING + " # QUESTION: A trained model already exists, do you want to train it again? (y/n) " + bcolors.WHITE
            user_reply = input(question)
        else:
            user_reply = "y"

        if user_reply != "y":
            self.model = load_model('models/'+self.dataset+'_KERAS_model.h5')
            return
        
        unique = np.unique(self.y_train_val)
        self.classes_len = len(self.classes)

        print(bcolors.OKGREEN + " # Input shape is: "+str(self.X_train_val.shape)+bcolors.WHITE)
        self.train_size = self.X_train_val.shape[0]

        self.build_model()

        checkpoint_path = 'models/'+self.dataset+'/training/cp.ckpt'
        checkpoint_dir = os.path.dirname(checkpoint_path)

        cp_callback = tf.keras.callbacks.ModelCheckpoint(filepath=checkpoint_path,
                                                save_weights_only=True,
                                                verbose=1)
        
        if self.network_spec == None:
            print(bcolors.OKGREEN + " # INFO: Start model training with networks specs ... "+bcolors.WHITE)
            self.model.fit(
                self.X_train_val, 
                self.y_train_val, 
                batch_size=int(self.X_train_val.shape[1]/10), 
                epochs=1, 
                validation_split=0.25, 
                shuffle=True,
                callbacks=[cp_callback])
        else:
            print(bcolors.OKGREEN + " # INFO: Start model training with networks specs ... "+bcolors.WHITE)
            batch_size = int(self.X_train_val.shape[1]*10) if self.network_spec["network"]["training"]["batch_size"] == "default" else int(self.network_spec["network"]["training"]["batch_size"])
            epochs = int(self.network_spec["network"]["training"]["epochs"])
            validation_split = 0.25 if self.network_spec["network"]["training"]["validation_split"] == "default" else float(self.network_spec["network"]["training"]["validation_split"])
            shuffle = True if self.network_spec["network"]["training"]["shuffle"] == "true" else False

            
            self.model.fit(
                self.X_train_val, 
                self.y_train_val, 
                batch_size=batch_size, 
                epochs=epochs, 
                validation_split=validation_split, 
                shuffle=shuffle,
                callbacks=[cp_callback])
        
        print(self.model.summary())
        
        #self.model = strip_pruning(self.model)
        tf.keras.utils.plot_model(
            self.model,
            to_file='models/'+self.dataset+'/model.png',
            show_shapes=True,
            show_dtype=True,
            show_layer_names=True,
            rankdir='TB',
            expand_nested=True,
            dpi=96,
            layer_range=None,
            show_layer_activations=True
        )
        
        w = self.model.layers[0].weights[0].numpy()
        h, b = np.histogram(w, bins=100)
        plt.figure(figsize=(7, 7))
        plt.bar(b[:-1], h, width=b[1] - b[0])
        plt.semilogy()
        print('% of zeros = {}'.format(np.sum(w == 0) / np.size(w)))

        if self.pruning:
            print(bcolors.OKGREEN + " # INFO: Going to prune model: "+bcolors.WHITE)
            self.exec_pruning()
        self.dump_json_for_bondmachine()
        self.get_json_model()
        self.build_graph()
        
        print("neural network parameters: ", self.neural_networks_params)
        input("Watch parameters")
        
        #print(bcolors.OKGREEN + " # input name", self.model.input.op.name+bcolors.WHITE)
        #print(bcolors.OKGREEN + " # output name", self.model.output.op.name+bcolors.WHITE)
        print(bcolors.OKGREEN + " # INFO: Training finished, saved model path: "+'models/'+self.dataset+'_KERAS_model.h5'+bcolors.WHITE)
        self.model.save('models/'+self.dataset+'/model.h5')
        #meta_graph_def = tf.train.export_meta_graph(filename='models/'+self.dataset+'_KERAS_model.meta')
        

    def dump_csv_prediction(self, predictions):
        results = []
        for pred in predictions:
            prediction = np.argmax(pred, axis=0)
            to_save = []
            for i in range(0, self.classes_len):
                to_save.append(pred[i])
                
            to_save.append(prediction)
            results.append(to_save)
            
        import csv
        fields = [] 

        for i in range(0, self.classes_len):
            fields.append('probability_'+str(i))
            
        fields.append('classification')

        with open("datasets/"+self.dataset+'_swprediction.csv', 'w') as f:
            write = csv.writer(f)
            write.writerow(fields)
            write.writerows(results)

    def exec_test(self):
        print(self.model.summary())
        y_keras = self.model.predict(self.X_test)
        np.save("datasets/"+self.dataset+'_y_keras.npy', y_keras)
        self.dump_csv_prediction(y_keras)
        #np.savetxt("datasets/"+self.dataset+'_swprediction.csv', y_keras, delimiter=",")
        # print(self.X_test)
        accuracy = format(accuracy_score(np.argmax(self.y_test, axis=1), np.argmax(y_keras, axis=1)))
        print(bcolors.OKGREEN + " # INFO: Accuracy is "+accuracy+bcolors.WHITE)
        user_reply = input(bcolors.WARNING + " # QUESTION: Model has been exported in JSON for Bondmachine (path is: models/"+self.dataset+"/modelBM.json), do you want to continue with HLS4ML? (y/n)"+bcolors.WHITE)
        if user_reply != "y":
            sys.exit(0)
            
        input(bcolors.OKGREEN+" # INFO: press enter to continue"+bcolors.WHITE)

    def exec_pruning(self):
        self.model.summary()
        
        pruning_params = {'pruning_schedule': PolynomialDecay(initial_sparsity=0.50, final_sparsity=0.80, begin_step=2000, end_step=4000)}
        model_for_pruning = tfmot.sparsity.keras.prune_low_magnitude(self.model, **pruning_params)
        
        model_for_pruning.compile(optimizer='adam',loss='categorical_crossentropy',metrics=['accuracy'])
        model_for_pruning.summary()
        callbacks = [tfmot.sparsity.keras.UpdatePruningStep()]
        batch_size = int(self.X_train_val.shape[1]*10) if self.network_spec["network"]["training"]["batch_size"] == "default" else int(self.network_spec["network"]["training"]["batch_size"])
        validation_split = 0.25 if self.network_spec["network"]["training"]["validation_split"] == "default" else float(self.network_spec["network"]["training"]["validation_split"])
        model_for_pruning.fit(
            self.X_train_val, 
            self.y_train_val,
            batch_size=batch_size,
            validation_split=validation_split,
            epochs=2,
            callbacks=callbacks)

        model_for_export = tfmot.sparsity.keras.strip_pruning(model_for_pruning)
        model_for_export.summary()
        
        self.model = model_for_export
        
    def isBoardSupported(self):

        for board in self.hls4ml_supported_boards:
            if board["name"] == self.fpga_board_name:
                return True
        
        return False

    def build_model_fpga(self):

        # change the date due to a Vivado bug
        # https://support.xilinx.com/s/question/0D52E00006uxy49SAA/vivado-fails-to-export-ips-with-the-error-message-bad-lexical-cast-source-type-value-could-not-be-interpreted-as-target?language=en_US
        
        try:
            subprocess.check_output("sudo timedatectl set-ntp false", shell=True)
            subprocess.check_output("sudo date -s '3 years ago'", shell=True)
        except subprocess.CalledProcessError as e:
            raise Exception(f"Command failed with exit code {e.returncode}") from e

        config = hls4ml.utils.config_from_keras_model(self.model, granularity='name')

        if self.fpga_board_name == None and self.fpga_part_number != None:
            for board in self.hls4ml_supported_boards:
                if  board["part"] == self.fpga_part_number:
                    self.fpga_board_name = board["name"]
        elif self.fpga_board_name != None and self.fpga_part_number == None:
            for board in self.hls4ml_supported_boards:
                if  board["name"] == self.fpga_board_name:
                    self.fpga_part_number = board["part"]

        print(bcolors.OKGREEN + " # INFO: fpga board name      "+str(self.fpga_board_name)+bcolors.WHITE)
        print(bcolors.OKGREEN + " # INFO: fpga part number     "+self.fpga_part_number+bcolors.WHITE)

        if self.isBoardSupported() == True:
            print(bcolors.OKGREEN + " # INFO: fpga board is supported, build also the firmware      "+str(self.fpga_board_name)+bcolors.WHITE)
            self.hls_model = hls4ml.converters.convert_from_keras_model(
                                                        self.model,
                                                        backend='VivadoAccelerator',
                                                        io_type='io_stream',
                                                        hls_config=config,
                                                        output_dir='models_fpga/'+self.dataset+'_hls4ml_prj',
                                                        board=self.fpga_board_name,
                                                        part=self.fpga_part_number)
        else:
            print(bcolors.OKGREEN + " # INFO: fpga board is not supported, build the IP module for      "+str(self.fpga_board_name)+bcolors.WHITE)
            self.hls_model = hls4ml.converters.convert_from_keras_model(
                                                        self.model,
                                                        backend='VivadoAccelerator',
                                                        io_type='io_stream',
                                                        hls_config=config,
                                                        output_dir='models_fpga/'+self.dataset+'_hls4ml_prj',
                                                        part=self.fpga_part_number)

        self.hls_model.compile()
        if self.isBoardSupported() == True:
            self.hls_model.build(csim=False, synth=True, export=True, bitfile=True)
        else:
            self.hls_model.build(csim=False, synth=True, export=True, bitfile=False)

        # change the date due to a Vivado bug
        # https://support.xilinx.com/s/question/0D52E00006uxy49SAA/vivado-fails-to-export-ips-with-the-error-message-bad-lexical-cast-source-type-value-could-not-be-interpreted-as-target?language=en_US
        try:
            subprocess.check_output("sudo timedatectl set-ntp true", shell=True)
        except subprocess.CalledProcessError as e:
            raise Exception(f"Command failed with exit code {e.returncode}") from e

parser = argparse.ArgumentParser(description="Arguments for training nn", formatter_class=argparse.ArgumentDefaultsHelpFormatter)
parser.add_argument("-d", "--dataset", help="dataset name")
parser.add_argument("-b", "--fpga_board_name", help="fpga board number")
parser.add_argument("-f", "--fpga_part_number", help="fpga part number")
parser.add_argument("-m", "--nn_model_type", help="neural network architecture")
args = vars(parser.parse_args())
dataset_name = args["dataset"]
fpga_part_number = args["fpga_part_number"]
fpga_board_name = args["fpga_board_name"]
nn_model_type = args["nn_model_type"]

if dataset_name == None or len(dataset_name.replace(" ", "")) == 0:
    print(" # ERROR: No dataset name has been specified. ")
    sys.exit(1)

if fpga_part_number == None and fpga_board_name == None:
    print(bcolors.OKGREEN+" # INFO: FPGA part number not specified, using default xc7z010clg400-1"+bcolors.WHITE)
    fpga_part_number = "xc7z010clg400-1"
    fpga_board_name = "ebaz4205"

if nn_model_type == None:
    nn_model_type = "MLP"

t = Trainer(fpga_part_number,fpga_board_name,nn_model_type)
t.initialize()
try:
    t.setup_data(dataset_name)
except Exception as e:
    print(" # An error occurred during setup data:", e)
    sys.exit(1)

t.exec_train()
t.exec_test()
t.build_model_fpga()
sys.exit()