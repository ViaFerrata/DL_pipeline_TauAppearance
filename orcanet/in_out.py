#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Utility code regarding reading user input, and writing output like logfiles.
"""

import os
import shutil
import h5py
import toml
import numpy as np
from datetime import datetime
from collections import namedtuple


def read_out_config_file(file):
    """
    Extract the variables of a model from the .toml file and convert them to a dict.

    Toml can not handle arrays with mixed types of variables, so some conversion are done.

    Parameters
    ----------
    file : str
        Path and name of the .toml file that defines the properties of the model.

    Returns
    -------
    keyword_arguments : dict
        Values for the OrcaNet scripts, as listed in the Configuration class.

    """
    file_content = toml.load(file)["config"]
    if "n_gpu" in file_content:
        file_content["n_gpu"][0] = int(file_content["n_gpu"][0])
    return file_content


def read_out_list_file(file):
    """
    Reads out a list file in .toml format containing the pathes to training
    and validation files and bring it into the proper format.

    Parameters
    ----------
    file : str
        Path to a .list file containing the paths to training and validation files to be used during training.

    Returns
    -------
    train_files : dict
        A dict containing the paths to the different training files given in the list_file.
        Example for the output format:
                {
                 "input_A" : ('path/to/set_A_train_file_1.h5', 'path/to/set_A_train_file_2.h5', ...)
                 "input_B" : ('path/to/set_B_train_file_1.h5', 'path/to/set_B_train_file_2.h5', ...)
                 ...
                }
    validation_files : dict
        Like the above but for validation files.

    Raises
    -------
    AssertionError
        If different inputs have a different number of training or validation files.

    """
    # a dict with inputnames as keys and dicts with the lists of train/val files as values
    file_content = toml.load(file)
    # TODO raise if the list does not have the proper format
    train_files, validation_files = {}, {}
    # no of train/val files in each input set
    n_train, n_val = [], []
    for input_key in file_content:
        train_files[input_key] = tuple(file_content[input_key]["train_files"])
        validation_files[input_key] = tuple(file_content[input_key]["validation_files"])
        n_train.append(len(train_files[input_key]))
        n_val.append(len(validation_files[input_key]))

    if not n_train.count(n_train[0]) == len(n_train):
        raise AssertionError("The specified training inputs do not all have the same number of files!")
    if not n_val.count(n_val[0]) == len(n_val):
        raise AssertionError("The specified validation inputs do not all have the same number of files!")
    return train_files, validation_files


def read_out_model_file(file):
    """
    Read out parameters for creating models with OrcaNet from a toml file.

    Parameters
    ----------
    file : str
        Path to the toml file.

    Returns
    -------
    modeldata : namedtuple
        Infos for building a predefined model with OrcaNet.

    """
    file_content = toml.load(file)["model"]
    nn_arch = file_content.pop("nn_arch")
    losses = file_content.pop("losses")

    class_type = ''
    str_ident = ''
    swap_4d_channels = None

    if "class_type" in file_content:
        class_type = file_content.pop("class_type")
    if "str_ident" in file_content:
        str_ident = file_content.pop("str_ident")
    if "swap_4d_channels" in file_content:
        swap_4d_channels = file_content.pop("swap_4d_channels")

    loss_opt = (losses, None)
    ModelData = namedtuple("ModelData", "nn_arch loss_opt class_type str_ident swap_4d_channels args")
    modeldata = ModelData(nn_arch, loss_opt, class_type, str_ident, swap_4d_channels, file_content)

    return modeldata


def write_full_logfile_startup(cfg):
    """
    Whenever the orca_train function is run, this logs all the input parameters in the full log file.

    Parameters
    ----------
    cfg : object Configuration
        Configuration object containing all the configurable options in the OrcaNet scripts.

    """
    logfile = cfg.main_folder + 'full_log.txt'
    with open(logfile, 'a+') as f_out:
        f_out.write('--------------------------------------------------------------------------------------------------------\n')
        f_out.write('----------------------------------'+str(datetime.now().strftime('%Y-%m-%d %H:%M:%S'))+'---------------------------------------------------\n\n')
        f_out.write("New execution of the orca_train function started with the following options:\n\n")
        f_out.write("List file path:\t"+cfg.get_list_file()+"\n")
        f_out.write("Given trainfiles in the .list file:\n")
        f_out.write(str(cfg.get_train_files())+"\n")
        f_out.write("Given validation files in the .list file:\n")
        f_out.write(str(cfg.get_val_files()) + "\n")
        f_out.write("\nConfiguration used:\n")
        for key in vars(cfg):
            if not key.startswith("_"):
                f_out.write("   {}:\t{}\n".format(key, getattr(cfg, key)))
        f_out.write("\nPrivate attributes:\n")
        for key in vars(cfg):
            if key.startswith("_"):
                f_out.write("   {}:\t{}\n".format(key, getattr(cfg, key)))
        f_out.write("\n")


def write_full_logfile(cfg, model, history_train, history_val, lr, epoch, files_dict):
    """
    Function for saving various information during training and validation to a .txt file.

    Parameters
    ----------
    cfg : object Configuration
        Configuration object containing all the configurable options in the OrcaNet scripts.
    files_dict : dict
        The name of every input as a key, the path to the n-th training file as values.

    """
    logfile = cfg.main_folder + 'full_log.txt'
    with open(logfile, 'a+') as f_out:
        f_out.write('---------------Epoch {} File {}-------------------------------------------------------------------------\n'.format(epoch[0], epoch[1]))
        f_out.write('\n')
        f_out.write('Current time: ' + str(datetime.now().strftime('%Y-%m-%d %H:%M:%S')) + '\n')
        f_out.write('Decayed learning rate to ' + str(lr) + ' before epoch ' + str(epoch[0]) +
                    ' and file ' + str(epoch[1]) + ')\n')
        f_out.write('Trained in epoch ' + str(epoch) + ' on file ' + str(epoch[1]) + ', ' + str(files_dict) + '\n')
        if history_val is not None:
            f_out.write('Validated in epoch ' + str(epoch) + ', file ' + str(epoch[1]) + ' on val_files ' + str(cfg.get_val_files()) + '\n')
        f_out.write('History for training / validating: \n')
        f_out.write('Train: ' + str(history_train.history) + '\n')
        if history_val is not None:
            f_out.write('Validation: ' + str(history_val) + ' (' + str(model.metrics_names) + ')' + '\n')
        f_out.write('\n')


def write_summary_logfile(cfg, epoch, model, history_train, history_val, lr):
    """
    Write to the summary.txt file in every trained model folder.

    Parameters
    ----------
    cfg : object Configuration
        Configuration object containing all the configurable options in the OrcaNet scripts.
    epoch : tuple(int, int)
        The number of the current epoch and the current filenumber.
    model : ks.model.Model
        Keras model instance of a neural network.
    history_train : Keras history object
        History object containing the history of the training, averaged over files.
    history_val : List
        List of validation losses for all the metrics, averaged over all validation files.
    lr : float
        The current learning rate of the model.

    """
    # get this for the epoch_number_float in the logfile
    steps_per_total_epoch, steps_cum = 0, [0]
    for f_size in cfg.get_file_sizes("train"):
        steps_per_file = int(f_size / cfg.batchsize)
        steps_per_total_epoch += steps_per_file
        steps_cum.append(steps_cum[-1] + steps_per_file)
    epoch_number_float = epoch[0] - (steps_per_total_epoch - steps_cum[epoch[1]]) / float(steps_per_total_epoch)

    # Write the logfile
    logfile_fname = cfg.main_folder + 'summary.txt'
    with open(logfile_fname, 'a+') as logfile:
        # Write the headline
        if os.stat(logfile_fname).st_size == 0:
            logfile.write('Epoch\tLR\t')
            for i, metric in enumerate(model.metrics_names):
                logfile.write("train_" + str(metric) + "\tval_" + str(metric))
                if i + 1 < len(model.metrics_names):
                    logfile.write("\t")
            logfile.write('\n')
        # Write the content: Epoch, LR, train_1, val_1, ...
        logfile.write("{:.4g}\t".format(float(epoch_number_float)))
        logfile.write("{:.4g}\t".format(float(lr)))
        for i, metric_name in enumerate(model.metrics_names):
            logfile.write("{:.4g}\t".format(float(history_train.history[metric_name][0])))
            if history_val is None:
                logfile.write("nan")
            else:
                logfile.write("{:.4g}".format(float(history_val[i])))
            if i + 1 < len(model.metrics_names):
                logfile.write("\t")
        logfile.write('\n')


def read_logfiles(summary_logfile):
    """
    Read out the data from the summary.txt file, and from all training log files in the log_train folder which
    is in the same directory as the summary.txt file.

    Parameters
    ----------
    summary_logfile : str
        Path of the summary.txt file in a model folder.

    Returns
    -------
    summary_data : numpy.ndarray
        Structured array containing the data from the summary.txt file.
    full_train_data : numpy.ndarray
        Structured array containing the data from all the training log files, merged into a single array.

    """
    summary_data = np.genfromtxt(summary_logfile, names=True, delimiter="\t")

    # list of all files in the log_train folder of this model
    log_train_folder = "/".join(summary_logfile.split("/")[:-1])+"/log_train/"
    files = os.listdir(log_train_folder)
    train_file_data = []
    for file in files:
        # file is something like "log_epoch_1_file_2.txt", extract the 1 and 2:
        epoch, file_no = [int(file.split(".")[0].split("_")[i]) for i in [2,4]]
        file_data = np.genfromtxt(log_train_folder+file, names=True, delimiter="\t")
        train_file_data.append([[epoch, file_no], file_data])
    train_file_data.sort()
    full_train_data = train_file_data[0][1]
    for [epoch, file_no], file_data in train_file_data[1:]:
        # file_data["Batch_float"]+=(epoch-1)
        full_train_data = np.append(full_train_data, file_data)
    return summary_data, full_train_data


def h5_get_number_of_rows(h5_filepath, datasets):
    """
    Gets the total number of rows of of a .h5 file.

    Multiple dataset names can be given as a list to check if they all have the same number of rows (axis 0).

    Parameters
    ----------
    h5_filepath : str
        filepath of the .h5 file.
    datasets : list
        The names of datasets in the file to check.

    Returns
    -------
    number_of_rows: int
        number of rows of the .h5 file in the first dataset.

    Raises
    ------
    AssertionError
        If the given datasets do not have the same no of rows.

    """
    with h5py.File(h5_filepath, 'r') as f:
        number_of_rows = [f[dataset].shape[0] for dataset in datasets]
    if not number_of_rows.count(number_of_rows[0]) == len(number_of_rows):
        err_msg = "Datasets do not have the same number of samples in file " + h5_filepath
        for i, dataset in enumerate(datasets):
            err_msg += "\nDataset: {}\tSamples: {}".format(dataset, number_of_rows[i])
        raise AssertionError(err_msg)
    return number_of_rows[0]


def use_node_local_ssd_for_input(train_files, val_files):
    """
    Copies the test and train files to the node-local ssd scratch folder and returns the new filepaths of the train and test data.
    Speeds up I/O and reduces RRZE network load.

    Parameters
    ----------
    train_files : dict
        Dict containing the train file pathes.
    val_files
        Dict containing the val file pathes.

    Returns
    -------
    train_files_ssd : dict
        Train dict with updated SSD /scratch filepaths.
    test_files_ssd : dict
        Val dict with updated SSD /scratch filepaths.

    """
    local_scratch_path = os.environ['TMPDIR']
    train_files_ssd, val_files_ssd = {}, {}

    for input_key in train_files:
        old_pathes = train_files[input_key]
        new_pathes = []
        for f_path in old_pathes:
            # copy to /scratch node-local SSD
            f_path_ssd = local_scratch_path + '/' + os.path.basename(f_path)
            print("Copying", f_path, "\nto", f_path_ssd)
            shutil.copy2(f_path, local_scratch_path)
            new_pathes.append(f_path_ssd)
        train_files_ssd[input_key] = new_pathes

    for input_key in val_files:
        old_pathes = val_files[input_key]
        new_pathes = []
        for f_path in old_pathes:
            # copy to /scratch node-local SSD
            f_path_ssd = local_scratch_path + '/' + os.path.basename(f_path)
            print("Copying", f_path, "\nto", f_path_ssd)
            shutil.copy2(f_path, local_scratch_path)
            new_pathes.append(f_path_ssd)
        val_files_ssd[input_key] = new_pathes

    print('Finished copying the input train/test data to the node-local SSD scratch folder.')
    return train_files_ssd, val_files_ssd