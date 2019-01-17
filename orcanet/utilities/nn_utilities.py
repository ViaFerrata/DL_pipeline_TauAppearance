#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Utility functions used for training a CNN."""

import warnings
import re
import numpy as np
import h5py
import os
import keras as ks
from functools import reduce

#------------- Functions used for supplying images to the GPU -------------#

def generate_batches_from_hdf5_file(filepath, batchsize, n_bins, class_type, str_ident, f_size=None, zero_center_image=None, yield_mc_info=False, swap_col=None):
    """
    Generator that returns batches of (multiple-) images ('xs') and labels ('ys') from single or multiple h5 files.
    :param list filepath: List that contains full filepath of the input h5 files, e.g. '/path/to/file/file.h5'.
    :param int batchsize: Size of the batches that should be generated. Ideally same as the chunksize in the h5 file.
    :param tuple n_bins: Number of bins for each dimension (x,y,z,t) in the h5 file.
    :param (int, str) class_type: Tuple with the umber of output classes and a string identifier to specify the exact output classes.
                                  I.e. (2, 'muon-CC_to_elec-CC')
    :param str str_ident: string identifier that specifies the projection type / model inputs in certain cases.
    :param int/None f_size: Specifies the filesize (#images) of the .h5 file if not the whole .h5 file
                       but a fraction of it (e.g. 10%) should be used for yielding the xs/ys arrays.
                       This is important if you run fit_generator(epochs>1) with a filesize (and hence # of steps) that is smaller than the .h5 file.
    :param ndarray zero_center_image: mean_image of the x dataset used for zero-centering.
    :param bool yield_mc_info: Specifies if mc-infos (y_values) should be yielded as well.
                               The mc-infos are used for evaluation after training and testing is finished.
    :param bool/str swap_col: Specifies, if the index of the columns for xs should be swapped. Necessary for 3.5D nets.
                          Currently available: 'yzt-x' -> [3,1,2,0] from [0,1,2,3]
    :return: tuple output: Yields a tuple which contains a full batch of images and labels (+ mc_info if yield_mc_info=True).
    """
    n_files = len(filepath)
    dimensions = {}
    for i in range(n_files):
        dimensions[i] = get_dimensions_encoding(n_bins[i], batchsize)

    swap_4d_channels_dict = {'yzt-x': (0, 2, 3, 4, 1), 'xyt-z': (0, 1, 2, 4, 3), 't-xyz': (0,4,1,2,3), 'tyz-x': (0,4,2,3,1)}

    while 1:
        f = {}
        for i in range(n_files):
            f[i] = h5py.File(filepath[i], 'r')

        if f_size is None: # Should be same for all files!
            f_size = len(f[0]['y']) # Take len of first file in filepaths, should be same for all files
            warnings.warn('f_size=None could produce unexpected results if the f_size used in fit_generator(steps=int(f_size / batchsize)) with epochs > 1 '
                          'is not equal to the f_size of the true .h5 file. Should be ok if you use the tb_callback.')

        n_entries = 0
        while n_entries <= (f_size - batchsize):
            # create numpy arrays of input data (features)
            xs = {}
            xs_list = [] # list of inputs for the Keras NN
            for i in range(n_files):
                xs[i] = f[i]['x'][n_entries : n_entries + batchsize]
                xs[i] = np.reshape(xs[i], dimensions[i]).astype(np.float32)

            if zero_center_image is not None:
                for i in range(n_files):
                    xs[i] = np.subtract(xs[i], zero_center_image[i])

            if swap_col is not None:

                # single image input
                if swap_col == 'yzt-x' or swap_col == 'xyt-z':
                    xs_list.append(np.transpose(xs, swap_4d_channels_dict[swap_col]))
                elif swap_col == 'xyz-t_and_yzt-x':
                    xs_list.append(xs[0]) # xyzt
                    xs_yzt_x = np.transpose(xs[0], swap_4d_channels_dict['yzt-x'])
                    xs_list.append(xs_yzt_x)

                elif 'xyz-t_and_yzt-x' + 'multi_input_single_train_tight-1_tight-2' in swap_col + str_ident:
                    xs_list.append(xs[0]) # xyz-t tight-1
                    xs_yzt_x_tight_1 = np.transpose(xs[0], swap_4d_channels_dict['yzt-x']) # yzt-x tight-1
                    xs_list.append(xs_yzt_x_tight_1)
                    xs_list.append(xs[1]) # xyz-t tight-2
                    xs_yzt_x_tight_2 = np.transpose(xs[1], swap_4d_channels_dict['yzt-x']) # yzt-x tight-2
                    xs_list.append(xs_yzt_x_tight_2)

                elif swap_col == 'xyz-t_and_xyz-c_single_input':
                    xyz_t_and_xyz_c = np.concatenate([xs[0], xs[1]], axis=-1)
                    xs_list = xyz_t_and_xyz_c # here, it's not a list since we have only one input image

                else: raise ValueError('The argument "swap_col"=' + str(swap_col) + ' is not valid.')

            else:
                for i in range(n_files):
                    xs_list.append(xs[i])

            # and mc info (labels). Since the labels are same (!!) for all the multiple files, use first file for this
            y_values = f[0]['y'][n_entries:n_entries+batchsize]
            y_values = np.reshape(y_values, (batchsize, y_values.shape[1]))

            if class_type[1] != 'track-shower':
                ys = get_regression_labels(y_values, class_type) # ys: dict which contains arrays for every output key

            else:
                ys = np.zeros((batchsize, class_type[0]), dtype=np.float32)
                # encode the labels such that they are all within the same range (and filter the ones we don't want for now)
                for c, y_val in enumerate(y_values): # Could be vectorized with numba, or use dataflow from tensorpack
                    ys[c] = encode_targets(y_val, class_type)

            # we have read one more batch from this file
            n_entries += batchsize

            output = (xs_list, ys) if yield_mc_info is False else (xs_list, ys) + (y_values,)

            yield output

        for i in range(n_files):
            f[i].close()


# def gen_batches_from_single_file(filepath, batchsize, n_bins, class_type, f_size=None, zero_center_image=None, yield_mc_info=False, swap_col=None):
#     """
#     Generator that returns batches of images ('xs') and labels ('ys') from a h5 file.
#     :param string filepath: Full filepath of the input h5 file, e.g. '/path/to/file/file.h5'.
#     :param int batchsize: Size of the batches that should be generated. Ideally same as the chunksize in the h5 file.
#     :param tuple n_bins: Number of bins for each dimension (x,y,z,t) in the h5 file.
#     :param (int, str) class_type: Tuple with the umber of output classes and a string identifier to specify the exact output classes.
#                                   I.e. (2, 'muon-CC_to_elec-CC')
#     :param int/None f_size: Specifies the filesize (#images) of the .h5 file if not the whole .h5 file
#                        but a fraction of it (e.g. 10%) should be used for yielding the xs/ys arrays.
#                        This is important if you run fit_generator(epochs>1) with a filesize (and hence # of steps) that is smaller than the .h5 file.
#     :param ndarray zero_center_image: mean_image of the x dataset used for zero-centering.
#     :param bool yield_mc_info: Specifies if mc-infos (y_values) should be yielded as well.
#                                The mc-infos are used for evaluation after training and testing is finished.
#     :param bool/str swap_col: Specifies, if the index of the columns for xs should be swapped. Necessary for 3.5D nets.
#                           Currently available: 'yzt-x' -> [3,1,2,0] from [0,1,2,3]
#     :return: tuple output: Yields a tuple which contains a full batch of images and labels (+ mc_info if yield_mc_info=True).
#     """
#     dimensions = get_dimensions_encoding(n_bins, batchsize)
#     swap_4d_channels_dict = {'yzt-x': (0, 2, 3, 4, 1), 'tyz-x': (0, 4, 2, 3, 1), 't-xyz': (0, 4, 1, 2, 3), 'xyt-z': (0, 1, 2, 4, 3)}
#
#     while 1:
#         f = h5py.File(filepath, 'r')
#         if f_size is None:
#             f_size = len(f['y'])
#             warnings.warn('f_size=None could produce unexpected results if the f_size used in fit_generator(steps=int(f_size / batchsize)) with epochs > 1 '
#                           'is not equal to the f_size of the true .h5 file. ')
#
#         n_entries = 0
#         while n_entries <= (f_size - batchsize):
#             # create numpy arrays of input data (features)
#             xs = f['x'][n_entries : n_entries + batchsize]
#             xs = np.reshape(xs, dimensions).astype(np.float32)
#
#             if zero_center_image is not None: xs = np.subtract(xs, zero_center_image[0])
#
#             if swap_col is not None:
#                 if swap_col == 'yzt-x' or swap_col == 'xyt-z':
#                     xs = np.transpose(xs, swap_4d_channels_dict[swap_col])
#                 elif swap_col == 'xyz-t_and_yzt-x':
#                     xs_xyz_t = xs
#                     xs_yzt_x = np.transpose(xs, swap_4d_channels_dict['yzt-x'])
#                     xs = [xs_xyz_t, xs_yzt_x]
#                 else: raise ValueError('The argument "swap_col"=' + str(swap_col) + ' is not valid.')
#
#             # and mc info (labels)
#             y_values = f['y'][n_entries:n_entries+batchsize]
#             y_values = np.reshape(y_values, (batchsize, y_values.shape[1])) #TODO simplify with (y_values, y_values.shape) ?
#
#             if class_type[1] != 'track-shower':
#                 ys = get_regression_labels(y_values, class_type) # ys: dict which contains arrays for every output key
#
#             else:
#                 ys = np.zeros((batchsize, class_type[0]), dtype=np.float32) # ys: arr
#                 # encode the labels such that they are all within the same range (and filter the ones we don't want for now)
#                 for c, y_val in enumerate(y_values): # Could be vectorized with numba, or use dataflow from tensorpack
#                     ys[c] = encode_targets(y_val, class_type)
#
#             # we have read one more batch from this file
#             n_entries += batchsize
#
#             output = (xs, ys) if yield_mc_info is False else (xs, ys) + (y_values,)
#
#             yield output
#
#         f.close() # this line of code is actually not reached if steps=f_size/batchsize


def get_dimensions_encoding(n_bins, batchsize):
    """
    Returns a dimensions tuple for 2,3 and 4 dimensional data.
    :param int batchsize: Batchsize that is used in generate_batches_from_hdf5_file().
    :param tuple n_bins: Declares the number of bins for each dimension (x,y,z).
                        If a dimension is equal to 1, it means that the dimension should be left out.
    :return: tuple dimensions: 2D, 3D or 4D dimensions tuple (integers).
    """
    n_bins_x, n_bins_y, n_bins_z, n_bins_t = n_bins[0], n_bins[1], n_bins[2], n_bins[3]
    if n_bins_x == 1:
        if n_bins_y == 1:
            print('Using 2D projected data without dimensions x and y')
            dimensions = (batchsize, n_bins_z, n_bins_t, 1)
        elif n_bins_z == 1:
            print('Using 2D projected data without dimensions x and z')
            dimensions = (batchsize, n_bins_y, n_bins_t, 1)
        elif n_bins_t == 1:
            print('Using 2D projected data without dimensions x and t')
            dimensions = (batchsize, n_bins_y, n_bins_z, 1)
        else:
            print('Using 3D projected data without dimension x')
            dimensions = (batchsize, n_bins_y, n_bins_z, n_bins_t, 1)

    elif n_bins_y == 1:
        if n_bins_z == 1:
            print('Using 2D projected data without dimensions y and z')
            dimensions = (batchsize, n_bins_x, n_bins_t, 1)
        elif n_bins_t == 1:
            print('Using 2D projected data without dimensions y and t')
            dimensions = (batchsize, n_bins_x, n_bins_z, 1)
        else:
            print('Using 3D projected data without dimension y')
            dimensions = (batchsize, n_bins_x, n_bins_z, n_bins_t, 1)

    elif n_bins_z == 1:
        if n_bins_t == 1:
            print('Using 2D projected data without dimensions z and t')
            dimensions = (batchsize, n_bins_x, n_bins_y, 1)
        else:
            print('Using 3D projected data without dimension z')
            dimensions = (batchsize, n_bins_x, n_bins_y, n_bins_t, 1)

    elif n_bins_t == 1:
        print('Using 3D projected data without dimension t')
        dimensions = (batchsize, n_bins_x, n_bins_y, n_bins_z, 1)

    else:
        # print 'Using full 4D data'
        dimensions = (batchsize, n_bins_x, n_bins_y, n_bins_z, n_bins_t)

    return dimensions


def get_regression_labels(y_values, class_type):
    """

    :param y_values:
    :param class_type
    :return:
    """
    ys = dict()
    y_values = y_values.astype(np.float32)

    if class_type[1] == 'energy_and_direction_and_bjorken-y':
        ys['dir_x'] = y_values[:, 5:6]
        ys['dir_y'] = y_values[:, 6:7]
        ys['dir_z'] = y_values[:, 7:8]
        ys['energy'] = y_values[:, 2:3]
        ys['bjorken-y'] = y_values[:, 4:5]

    elif class_type[1] == 'energy_dir_bjorken-y_errors':
        particle_type, is_cc = y_values[:, 1], y_values[:, 3]
        elec_nc_bool_id = np.logical_and(np.abs(particle_type) == 12, is_cc == 0)
        y_values[elec_nc_bool_id, 2] = y_values[elec_nc_bool_id, 2] * y_values[elec_nc_bool_id, 4] # correct energy to visible energy
        y_values[elec_nc_bool_id, 4] = 1 # set bjorken-y for elec_nc events to 1

        ys['dir_x'], ys['dir_x_err'] = y_values[:, 5:6], y_values[:, 5:6]
        ys['dir_y'], ys['dir_y_err'] = y_values[:, 6:7], y_values[:, 6:7]
        ys['dir_z'], ys['dir_z_err'] = y_values[:, 7:8], y_values[:, 7:8]
        ys['e'], ys['e_err'] = y_values[:, 2:3], y_values[:, 2:3]
        ys['by'], ys['by_err'] = y_values[:, 4:5], y_values[:, 4:5]

    elif class_type[1] == 'energy_dir_bjorken-y_vtx_errors':
        particle_type, is_cc = y_values[:, 1], y_values[:, 3]
        elec_nc_bool_id = np.logical_and(np.abs(particle_type) == 12, is_cc == 0)
        y_values[elec_nc_bool_id, 2] = y_values[elec_nc_bool_id, 2] * y_values[
            elec_nc_bool_id, 4]  # correct energy to visible energy
        y_values[elec_nc_bool_id, 4] = 1  # set bjorken-y for elec_nc events to 1

        ys['dx'], ys['dx_err'] = y_values[:, 5:6], y_values[:, 5:6] # dir
        ys['dy'], ys['dy_err'] = y_values[:, 6:7], y_values[:, 6:7]
        ys['dz'], ys['dz_err'] = y_values[:, 7:8], y_values[:, 7:8]
        ys['e'], ys['e_err'] = y_values[:, 2:3], y_values[:, 2:3]
        ys['by'], ys['by_err'] = y_values[:, 4:5], y_values[:, 4:5]

        ys['vx'], ys['vx_err'] = y_values[:, 10:11], y_values[:, 10:11] # vtx
        ys['vy'], ys['vy_err'] = y_values[:, 11:12], y_values[:, 11:12]
        ys['vz'], ys['vz_err'] = y_values[:, 12:13], y_values[:, 12:13]
        ys['vt'], ys['vt_err'] = y_values[:, 13:14], y_values[:, 13:14]

    else:
        raise ValueError('The regression label ' + str(class_type[1]) + ' in class_type[1] is not available.')

    return ys


def encode_targets(y_val, class_type):
    """
    Encodes the labels (classes) of the images.
    :param ndarray(ndim=1) y_val: Array that contains ALL event class information for one event.
           ---------------------------------------------------------------------------------------------------------------------------------------
           Current content: [event_id -> 0, particle_type -> 1, energy -> 2, isCC -> 3, bjorkeny -> 4, dir_x/y/z -> 5/6/7, time -> 8, run_id -> 9]
           ---------------------------------------------------------------------------------------------------------------------------------------
    :param (int, str) class_type: Tuple with the umber of output classes and a string identifier to specify the exact output classes.
                                  I.e. (2, 'muon-CC_to_elec-CC')
    :return: ndarray(ndim=1) train_y: Array that contains the encoded class label information of the input event.
    """
    def get_class_up_down_categorical(dir_z, n_neurons):
        """
        Converts the zenith information (dir_z) to a binary up/down value.
        :param float32 dir_z: z-direction of the event_track (which contains dir_z).
        :param int n_neurons: defines the number of neurons in the last cnn layer that should be used with the categorical array.
        :return ndarray(ndim=1) y_cat_up_down: categorical y ('label') array which can be fed to a NN.
                                               E.g. [0],[1] for n=1 or [0,1], [1,0] for n=2
        """
        # analyze the track info to determine the class number
        up_down_class_value = int(np.sign(dir_z)) # returns -1 if dir_z < 0, 0 if dir_z==0, 1 if dir_z > 0

        if up_down_class_value == 0:
            print('Warning: Found an event with dir_z==0. Setting the up-down class randomly.')
            # maybe [0.5, 0.5], but does it make sense with cat_crossentropy?
            up_down_class_value = np.random.randint(2)

        if up_down_class_value == -1: up_down_class_value = 0 # Bring -1,1 values to 0,1

        y_cat_up_down = np.zeros(n_neurons, dtype='float32')

        if n_neurons == 1:
            y_cat_up_down[0] = up_down_class_value # 1 or 0 for up/down
        else:
            y_cat_up_down[up_down_class_value] = 1 # [0,1] or [1,0] for up/down

        return y_cat_up_down


    def convert_particle_class_to_categorical(particle_type, is_cc, num_classes=4):
        """
        Converts the possible particle types (elec/muon/tau , NC/CC) to a categorical type that can be used as tensorflow input y
        :param int particle_type: Specifies the particle type, i.e. elec/muon/tau (12, 14, 16). Negative values for antiparticles.
        :param int is_cc: Specifies the interaction channel. 0 = NC, 1 = CC.
        :param int num_classes: Specifies the total number of classes that will be discriminated later on by the CNN. I.e. 2 = elec_NC, muon_CC.
        :return: ndarray(ndim=1) categorical: returns the categorical event type. I.e. (particle_type=14, is_cc=1) -> [0,0,1,0] for num_classes=4.
        """
        if num_classes == 4:
            particle_type_dict = {(12, 0): 0, (12, 1): 1, (14, 1): 2, (16, 1): 3}  # 0: elec_NC, 1: elec_CC, 2: muon_CC, 3: tau_CC
        else:
            raise ValueError('A number of classes !=4 is currently not supported!')

        category = int(particle_type_dict[(abs(particle_type), is_cc)])
        categorical = np.zeros(num_classes, dtype='int8') # TODO try bool
        categorical[category] = 1

        return categorical

    if class_type[1] == 'track-shower':
        assert class_type[0] == 2
        categorical_type = convert_particle_class_to_categorical(y_val[1], y_val[3], num_classes=4)
        train_y = np.zeros(class_type[0], dtype='float32')

        if categorical_type[2] == 1: # only a muon-CC event is a track
            train_y[1] = 1 # track
        else:
            train_y[0] = 1 # shower

    elif class_type[1] == 'up_down':
        train_y = get_class_up_down_categorical(y_val[7], class_type[0])

    elif class_type[1] == 'tau-CC_vs_other_neutrinos':
        categorical_type = convert_particle_class_to_categorical(y_val[1], y_val[3], num_classes=4) # yields [0/1,0/1,0/1,0/1]; elec_NC, elec_CC, muon_CC, tau_CC
        train_y = np.zeros(class_type[0], dtype='float32')

        if class_type[0] == 1:
            if categorical_type[3] != 0:
                train_y[0] = categorical_type[3]

        else:
            assert class_type[0] == 2
            train_y[0] = categorical_type[3]
            if categorical_type[3] != 1:
                train_y[1] = 1

    else:
        print("Class type " + str(class_type) + " not supported!")
        return y_val

    return train_y

# ------------- Functions used for supplying images to the GPU -------------#


# ------------- Functions for preprocessing -------------#

def load_zero_center_data(cfg):
    """
    Gets the xs_mean array(s) that can be used for zero-centering.

    The arrays are either loaded from a previously saved .npz file or they are calculated on the fly by
    calculating the mean value per bin for the given training files. The name of the saved image is derived from the
    name of the list file which was given to the cfg.

    Parameters
    ----------
    cfg : Object Settings
        Contains all the configurable options in the OrcaNet scripts.

    Returns
    -------
    xs_mean : list(ndarray)
        List of ndarray(s) that contains the mean_image of the x dataset (1 array per model input).
        Can be used for zero-centering later on.

    """
    train_files = cfg.get_train_files()
    zero_center_folder = cfg.zero_center_folder
    train_files_list_name = os.path.basename(cfg.get_list_file())

    xs_mean = []
    # loop over multiple input data files for a single event, each input needs its own xs_mean
    for i in range(len(train_files[0][0])):

        # load the filepaths of all precalculated zero_center .npz files, which contain the xs_mean
        zero_center_files = load_fpaths_of_existing_zero_center_files(zero_center_folder)
        # Collect all filepaths of the train_files for this projection in an array
        all_train_files_for_ip_i = get_fpaths_for_train_files_input_i(train_files, i)

        # get the xs_mean for this input number i, if it exists in any of the files in the zero_center_folder
        xs_mean_for_ip_i = get_precalculated_xs_mean_if_exists(zero_center_files, all_train_files_for_ip_i)

        if xs_mean_for_ip_i is not None:
            print('Loading an existing xs_mean_array for model input ' + str(i) + ' in order to zero_center the data!')
            xs_mean.append(xs_mean_for_ip_i)

        else:
            print('Calculating the xs_mean_array for model input ' + str(i) + ' in order to zero_center the data!')
            # if the train dataset is split over multiple files, we need to average over the single xs_mean_for_ip arrays.
            xs_mean_for_ip_arr_i = None
            for j in range(len(train_files)):
                filepath_j = train_files[j][0][i]  # j is the index of the j-th train file, i the index of the i-th input
                xs_mean_for_ip_i_step = get_mean_image(filepath_j, cfg.n_gpu[0])

                if xs_mean_for_ip_arr_i is None:
                    xs_mean_for_ip_arr_i = np.zeros((len(train_files),) + xs_mean_for_ip_i_step.shape, dtype=np.float64)
                xs_mean_for_ip_arr_i[j] = xs_mean_for_ip_i_step

            xs_mean_for_ip_i = np.mean(xs_mean_for_ip_arr_i, axis=0, dtype=np.float64).astype(np.float32) if len(train_files) > 1 else xs_mean_for_ip_arr_i[0]
            filename = zero_center_folder + train_files_list_name + '_' + str(i) + '.npz'
            np.savez(filename, xs_mean=xs_mean_for_ip_i, zero_center_used_ip_files=all_train_files_for_ip_i)
            print('Saved the xs_mean array for input ' + str(i) + ' with shape', xs_mean_for_ip_i.shape, ' to ', filename)

        xs_mean.append(xs_mean_for_ip_i)

    return xs_mean


def load_fpaths_of_existing_zero_center_files(zero_center_folder):
    """
    Loads the filepaths of all precalculated zero_center_files (.npz) in the zero_center_folder if they exist.

    Parameters
    ----------
    zero_center_folder : str
        Full path to the folder where the zero_centering arrays are / should be stored.

    Returns
    -------
    zero_center_files : list
        List that contains all filepaths of precalculated zero_center files.
        Can be empty, if no zero_center_files exist in that directory.

    """
    zero_center_files = []
    if os.path.isdir(zero_center_folder):
        for file in os.listdir(zero_center_folder):
            if file.endswith('.npz'):
                zero_center_files.append(zero_center_folder + file)
    else:
        os.mkdir(zero_center_folder)

    return zero_center_files


def get_fpaths_for_train_files_input_i(train_files, i):
    """
    Gets all filepaths of the train_files for the i-th input and puts them into an array.

    Parameters
    ----------
    train_files : list
        List of training files.
    i : int
        Integer for the i-th file input of the network.

    Returns
    -------
    all_train_files_for_ip_i : ndarray
        Array that contains the filepaths of all train_files for the i-th input.

    """
    all_train_files_for_ip_i_list = []
    for j in range(len(train_files)):
        all_train_files_for_ip_i_list.append(train_files[j][0][i])

    all_train_files_for_ip_i = np.array(all_train_files_for_ip_i_list)

    return all_train_files_for_ip_i


def get_precalculated_xs_mean_if_exists(zero_center_files, all_train_files_for_ip_i):
    """
    Function that searches for precalculated xs_mean arrays in the already existing zero_center_files.

    Specifically, the function opens every zero_center_file (.npz) and checks if the 'zero_center_used_ip_files' array
    is the same as the 'all_train_files_for_ip_i' array.

    Parameters
    ----------
    zero_center_files : list
        List that contains all filepaths of precalculated zero_center files.
    all_train_files_for_ip_i : ndarray
        Array that contains the filepaths of all train_files for the i-th input.

    Returns
    -------
    xs_mean_for_ip_i : None/ndarray
        Returns the xs_mean_for_ip_i array if it exists somewhere in the zero_center_files. If not, returns None.

    """
    xs_mean_for_ip_i = None
    for file in zero_center_files:
        print(file)
        zero_center_used_ip_files = np.load(file)['zero_center_used_ip_files']
        if np.array_equal(zero_center_used_ip_files, all_train_files_for_ip_i):
            xs_mean_for_ip_i = np.load(file)['xs_mean']
            break

    return xs_mean_for_ip_i


def get_mean_image(filepath, n_gpu):
    """
    Returns the mean_image of a xs dataset.
    Calculating still works if xs is larger than the available memory and also if the file is compressed!
    :param str filepath: Filepath of the data upon which the mean_image should be calculated.
    :param filepath: Filepath of the input data, used as a str for saving the xs_mean_image.
    :param int n_gpu: Number of used gpu's that is related to how much RAM is available (16G per GPU).
    :return: ndarray xs_mean: mean_image of the x dataset. Can be used for zero-centering later on.
    """
    f = h5py.File(filepath, "r")

    # check available memory and divide the mean calculation in steps
    total_memory = n_gpu * 8e9  # In bytes. Take 1/2 of what is available per GPU (16G), just to make sure.
    filesize = get_array_memsize(f['x'])

    steps = int(np.ceil(filesize/total_memory))
    n_rows = f['x'].shape[0]
    stepsize = int(n_rows / float(steps))

    xs_mean_arr = None

    for i in range(steps):
        print('Calculating the mean_image of the xs dataset in step ' + str(i) + " of " + str(steps))
        if xs_mean_arr is None:  # create xs_mean_arr that stores intermediate mean_temp results
            xs_mean_arr = np.zeros((steps, ) + f['x'].shape[1:], dtype=np.float64)

        if i == steps-1 or steps == 1:  # for the last step, calculate mean till the end of the file
            xs_mean_temp = np.mean(f['x'][i * stepsize: n_rows], axis=0, dtype=np.float64)
        else:
            xs_mean_temp = np.mean(f['x'][i*stepsize: (i+1) * stepsize], axis=0, dtype=np.float64)
        xs_mean_arr[i] = xs_mean_temp

    xs_mean = np.mean(xs_mean_arr, axis=0, dtype=np.float64).astype(np.float32)

    return xs_mean


def get_array_memsize(array):
    """
    Calculates the approximate memory size of an array.
    :param ndarray array: an array.
    :return: float memsize: size of the array in bytes.
    """
    shape = array.shape
    n_numbers = reduce(lambda x, y: x*y, shape)  # number of entries in an array
    precision = 8  # Precision of each entry, typically uint8 for xs datasets
    memsize = (n_numbers * precision) / float(8)  # in bytes

    return memsize


# ------------- Functions for preprocessing -------------#


# ------------- Various other functions -------------#

def get_modelname(n_bins, class_type, nn_arch, swap_4d_channels, str_ident=''):
    """
    Derives the name of a model based on its number of bins and the class_type tuple.
    The final modelname is defined as 'model_Nd_proj_class_type[1]'.
    E.g. 'model_3d_xyz_muon-CC_to_elec-CC'.
    :param list(tuple) n_bins: Number of bins for each dimension (x,y,z,t) of the training images. Can contain multiple n_bins tuples.
    :param (int, str) class_type: Tuple that declares the number of output classes and a string identifier to specify the exact output classes.
                                  I.e. (2, 'muon-CC_to_elec-CC')
    :param str nn_arch: String that declares which neural network model architecture is used.
    :param None/str swap_4d_channels: For 4D data input (3.5D models). Specifies the projection type.
    :param str str_ident: Optional str identifier that gets appended to the modelname.
    :return: str modelname: Derived modelname.
    """
    modelname = 'model_' + nn_arch + '_'

    projection = ''
    for i, bins in enumerate(n_bins):

        dim = 4- bins.count(1)
        if i > 0: projection += '_and_'
        projection += str(dim) + 'd_'

        if bins.count(1) == 0 and i == 0: # for 4D input # TODO FIX BUG XYZT AFTER NAME
            if swap_4d_channels is not None:
                projection += swap_4d_channels
            else:
                projection += 'xyz-c' if bins[3] == 31 else 'xyz-t'

        else: # 2D/3D input
            if bins[0] > 1: projection += 'x'
            if bins[1] > 1: projection += 'y'
            if bins[2] > 1: projection += 'z'
            if bins[3] > 1: projection += 't'

    str_ident = '_' + str_ident if str_ident is not '' else str_ident
    modelname += projection + '_' + class_type[1] + str_ident

    return modelname

#------------- Various other functions -------------#


#------------- Classes -------------#

class TensorBoardWrapper(ks.callbacks.TensorBoard):
    """Up to now (05.10.17), Keras doesn't accept TensorBoard callbacks with validation data that is fed by a generator.
     Supplying the validation data is needed for the histogram_freq > 1 argument in the TB callback.
     Without a workaround, only scalar values (e.g. loss, accuracy) and the computational graph of the model can be saved.

     This class acts as a Wrapper for the ks.callbacks.TensorBoard class in such a way,
     that the whole validation data is put into a single array by using the generator.
     Then, the single array is used in the validation steps. This workaround is experimental!"""
    def __init__(self, batch_gen, nb_steps, **kwargs):
        super(TensorBoardWrapper, self).__init__(**kwargs)
        self.batch_gen = batch_gen # The generator.
        self.nb_steps = nb_steps   # Number of times to call next() on the generator.

    def on_epoch_end(self, epoch, logs):
        # Fill in the `validation_data` property.
        # After it's filled in, the regular on_epoch_end method has access to the validation_data.
        imgs, tags = None, None
        for s in range(self.nb_steps):
            ib, tb = next(self.batch_gen)
            if imgs is None and tags is None:
                imgs = np.zeros(((self.nb_steps * ib.shape[0],) + ib.shape[1:]), dtype=np.float32)
                tags = np.zeros(((self.nb_steps * tb.shape[0],) + tb.shape[1:]), dtype=np.uint8)
            imgs[s * ib.shape[0]:(s + 1) * ib.shape[0]] = ib
            tags[s * tb.shape[0]:(s + 1) * tb.shape[0]] = tb
        self.validation_data = [imgs, tags, np.ones(imgs.shape[0]), 0.0]
        return super(TensorBoardWrapper, self).on_epoch_end(epoch, logs)


class BatchLevelPerformanceLogger(ks.callbacks.Callback):
    """
    TODO
    """
    # Gibt loss aus über alle :display batches, gemittelt über die letzten :display batches
    def __init__(self, train_files, batchsize, display, model, folder_name, epoch, flush_after_n_lines):
        """

        Parameters
        ----------
        train_files
        batchsize
        display
        model
        folder_name
        epoch
        flush_after_n_lines : int
            After how many lines the file should be flushed. -1 for flush at the end of the epoch only.

        """
        ks.callbacks.Callback.__init__(self)
        self.display = display
        self.epoch_number = epoch[0]
        self.f_number = epoch[1]
        self.model = model
        self.flush = flush_after_n_lines

        self.seen = 0
        self.logfile_train_fname = folder_name + '/log_train/log_epoch_' + str(epoch[0]) + '_file_' + str(epoch[1]) + '.txt'
        self.loglist = []

        self.cum_metrics = {}
        for metric in self.model.metrics_names: # set up dict with all model metrics
            self.cum_metrics[metric] = 0

        self.steps_per_total_epoch, self.steps_cum = 0, [0]
        for f, f_size in train_files:
            steps_per_file = int(f_size / batchsize)
            self.steps_per_total_epoch += steps_per_file
            self.steps_cum.append(self.steps_cum[-1] + steps_per_file)

        with open(self.logfile_train_fname, 'w') as logfile_train:
            logfile_train.write('Batch\tBatch_float\t')
            for i, metric in enumerate(self.model.metrics_names):
                # write columns for all losses / metrics
                logfile_train.write(metric)
                if i + 1 < len(self.model.metrics_names): logfile_train.write('\t')  # newline \n is already written in the batch_statistics

    def on_batch_end(self, batch, logs={}):
        self.seen += 1
        for metric in self.model.metrics_names:
            self.cum_metrics[metric] += logs.get(metric)

        if self.seen % self.display == 0:
            batchnumber_float = (self.seen - self.display / 2.) / float(self.steps_per_total_epoch) + self.epoch_number - 1 \
                                + (self.steps_cum [self.f_number-1] / float(self.steps_per_total_epoch))
                                # offset if the currently trained file is not the first one
                                #+ (self.f_number-1) * (1/float(self.n_train_files)) # start from zero # only works if all train files have approximately the same number of entries
            line = '\n{0}\t{1}'.format(self.seen, batchnumber_float)
            for metric in self.model.metrics_names:
                line = line + '\t' + str(self.cum_metrics[metric] / self.display)
                self.cum_metrics[metric] = 0
            self.loglist.append(line)

            if self.flush != -1 and self.display % self.flush == 0:
                with open(self.logfile_train_fname, 'a') as logfile_train:
                    for batch_statistics in self.loglist:
                        logfile_train.write(batch_statistics)
                    self.loglist=[]
                    logfile_train.flush()
                    os.fsync(logfile_train.fileno())

    def on_epoch_end(self, batch, logs={}):
        # on epoch end here means that this is called after one fit_generator loop in Keras is finished.
        with open(self.logfile_train_fname, 'a') as logfile_train:
            for batch_statistics in self.loglist:
                logfile_train.write(batch_statistics)
            logfile_train.flush()
            os.fsync(logfile_train.fileno())


#------------- Classes -------------#