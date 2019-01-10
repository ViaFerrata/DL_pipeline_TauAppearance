#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Scripts for making specific models.
"""

import keras as ks

from model_archs.short_cnn_models import create_vgg_like_model_multi_input_from_single_nns, create_vgg_like_model
from model_archs.wide_resnet import create_wide_residual_network
from utilities.losses import *
from utilities.multi_gpu.multi_gpu import get_available_gpus, make_parallel, print_mgpu_modelsummary


def parallelize_model_to_n_gpus(model, n_gpu, batchsize, loss_functions, optimizer, metrics, loss_weight):
    """
    Parallelizes the nn-model to multiple gpu's.

    Currently, up to 4 GPU's at Tiny-GPU are supported.

    Parameters
    ----------
    model : ks.model.Model
        Keras model of a neural network.
    n_gpu : tuple(int, str)
        Number of gpu's that the model should be parallelized to [0] and the multi-gpu mode (e.g. 'avolkov') [1].
    batchsize : int
        Batchsize that is used for the training / inferencing of the cnn.
    loss_functions : dict/str
        Dict/str with loss functions that should be used for each nn output. # TODO fix, make single loss func also use dict
    optimizer : ks.optimizers
        Keras optimizer instance, currently either "Adam" or "SGD".
    metrics : dict/str/None
        Dict/str with metrics that should be used for each nn output.
    loss_weight : dict/None
        Dict with loss weights that should be used for each sub-loss.

    Returns
    -------
    model : ks.models.Model
        The parallelized Keras nn instance (multi_gpu_model).
    batchsize : int
        The new batchsize scaled by the number of used gpu's.

    """
    if n_gpu[1] == 'avolkov':
        if n_gpu[0] == 1:
            return model, batchsize
        else:
            assert n_gpu[0] > 1 and isinstance(n_gpu[0], int), 'You probably made a typo: n_gpu must be an int with n_gpu >= 1!'

            gpus_list = get_available_gpus(n_gpu[0])
            ngpus = len(gpus_list)
            print('Using GPUs: {}'.format(', '.join(gpus_list)))
            batchsize = batchsize * ngpus

            # Data-Parallelize the model via function
            model = make_parallel(model, gpus_list, usenccl=False, initsync=True, syncopt=False, enqueue=False)
            print_mgpu_modelsummary(model)

            model.compile(loss=loss_functions, optimizer=optimizer, metrics=metrics, loss_weights=loss_weight)  # TODO check if necessary

            return model, batchsize

    else:
        raise ValueError('Currently, no multi_gpu mode other than "avolkov" is available.')


def build_nn_model(nn_arch, n_bins, class_type, swap_4d_channels, str_ident):
    """
    Function that builds a Keras nn model of a specific type.

    Parameters
    ----------
    nn_arch : str
        Architecture of the neural network.
    n_bins : list(tuple(int))
        Declares the number of bins for each dimension (e.g. (x,y,z,t)) in the train- and testfiles.
    class_type : tuple(int, str)
        Declares the number of output classes / regression variables and a string identifier to specify the exact output classes.
    swap_4d_channels : None/str
        For 4D data input (3.5D models). Specifies, if the channels of the 3.5D net should be swapped.
    str_ident : str
        Optional string identifier that gets appended to the modelname. Useful when training models which would have
        the same modelname. Also used for defining models and projections!

    Returns
    -------
    model : ks.models.Model
        A Keras nn instance.

    """
    if nn_arch == 'WRN':
        model = create_wide_residual_network(n_bins[0], nb_classes=class_type[0], n=1, k=1, dropout=0.2, k_size=3, swap_4d_channels=swap_4d_channels)

    elif nn_arch == 'VGG':
        if 'multi_input_single_train' in str_ident:
            dropout=(0,0.1)
            model = create_vgg_like_model_multi_input_from_single_nns(n_bins, str_ident, nb_classes=class_type[0],
                                                                      dropout=dropout, swap_4d_channels=swap_4d_channels)

        else:
            dropout=0.0
            n_filters=(64, 64, 64, 64, 64, 64, 128, 128, 128, 128)
            model = create_vgg_like_model(n_bins, class_type, dropout=dropout,
                                          n_filters=n_filters, swap_4d_channels=swap_4d_channels) # 2 more layers

    else: raise ValueError('Currently, only "WRN" or "VGG" are available as nn_arch')

    return model


def get_optimizer_info(loss_opt, optimizer='adam'):
    """
    Returns optimizer information for the training procedure.

    Parameters
    ----------
    loss_opt : tuple
        A Tuple with len=2.
        loss_opt[0]: dict with dicts of loss functions and optionally weights that should be used for each nn output.
            Typically read in from a .toml file.
            Format: { loss : { function, weight } }
        loss_opt[1]: dict with metrics that should be used for each nn output.
    optimizer : str
        Specifies, if "Adam" or "SGD" should be used as optimizer.

    Returns
    -------
    loss_functions : dict
        Cf. loss_opt[0].
    metrics : dict
        Cf. loss_opt[1].
    loss_weight : dict
        Cf. loss_opt[2].
    optimizer : ks.optimizers
        Keras optimizer instance, currently either "Adam" or "SGD".

    """
    if optimizer == 'adam':
        optimizer = ks.optimizers.Adam(beta_1=0.9, beta_2=0.999, epsilon=0.1, decay=0.0) # epsilon=1 for deep networks
    elif optimizer == "sgd":
        optimizer = ks.optimizers.SGD(momentum=0.9, decay=0, nesterov=True)
    else:
        raise NameError("Unknown optimizer name ({})".format(optimizer))
    custom_objects = get_all_loss_functions()
    loss_functions, loss_weight = {},{}
    for loss_key in loss_opt[0].keys():
        # Replace function string with the actual function if it is custom
        if loss_opt[0][loss_key]["function"] in custom_objects:
            loss_function=custom_objects[loss_opt[0][loss_key]["function"]]
        else:
            loss_function=loss_opt[0][loss_key]["function"]
        # Use given weight, else use default weight of 1
        if "weight" in loss_opt[0][loss_key]:
            weight = loss_opt[0][loss_key]["weight"]
        else:
            weight = 1.0
        loss_functions[loss_key] = loss_function
        loss_weight[loss_key] = weight
    metrics = loss_opt[1] if not loss_opt[1] is None else []

    return loss_functions, metrics, loss_weight, optimizer


def build_or_load_nn_model(epoch, folder_name, nn_arch, n_bins, class_type, swap_4d_channels, str_ident, loss_opt, n_gpu, batchsize):
    """
    Function that either builds (epoch = 0) a Keras nn model, or loads an existing one from the folder structure.

    Parameters
    ----------
    epoch : tuple(int, int)
        Declares if a previously trained model or a new model (=0) should be loaded, more info in the execute_nn function.
    folder_name : str
        Name of the main folder.
    nn_arch : str
        Architecture of the neural network.
    n_bins : list(tuple(int))
        Declares the number of bins for each dimension (e.g. (x,y,z,t)) in the train- and testfiles.
    class_type : tuple(int, str)
        Declares the number of output classes / regression variables and a string identifier to specify the exact output classes.
    swap_4d_channels : None/str
        For 4D data input (3.5D models). Specifies, if the channels of the 3.5D net should be swapped.
    str_ident : str
        Optional string identifier that gets appended to the modelname. Useful when training models which would have
        the same modelname. Also used for defining models and projections!

    Returns
    -------
    model : ks.models.Model
        A Keras nn instance.

    """
    if epoch[0] == 0:
        model = build_nn_model(nn_arch, n_bins, class_type, swap_4d_channels, str_ident)
    else:
        path_of_model = folder_name + '/saved_models/model_epoch_' + str(epoch[0]) + '_file_' + str(epoch[1]) + '.h5'
        model = ks.models.load_model(path_of_model, custom_objects=get_all_loss_functions())

    loss_functions, metrics, loss_weight, optimizer = get_optimizer_info(loss_opt, optimizer='adam')
    model, batchsize = parallelize_model_to_n_gpus(model, n_gpu, batchsize, loss_functions, optimizer, metrics,
                                                   loss_weight)
    model.summary()
    # model.compile(loss=loss_functions, optimizer=model.optimizer, metrics=model.metrics, loss_weights=loss_weight)
    if epoch[0] == 0:
        model.compile(loss=loss_functions, optimizer=optimizer, metrics=metrics, loss_weights=loss_weight)

    return model

