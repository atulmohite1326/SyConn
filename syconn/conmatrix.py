# -*- coding: utf-8 -*-
import os
import re

import numpy as np
import seaborn.apionly as sns
from mpl_toolkits.axes_grid1 import make_axes_locatable
from numpy import array as arr

from syconn.processing.cell_types import load_celltype_feats,\
    load_celltype_probas, get_id_dict_from_skel_ids, load_celltype_gt
from syconn.processing.learning_rfc import cell_classification
from syconn.utils.datahandler import get_filepaths_from_dir, write_obj2pkl,\
    load_pkl2obj
from syconn.utils import annotationUtils as au, newskeleton
import matplotlib
import matplotlib.pyplot as plt
from matplotlib import pyplot as pp
from matplotlib import gridspec
import matplotlib.colors as mcolors
__author__ = 'pschuber'


def make_colormap(seq):
    """Return a LinearSegmentedColormap
    seq: a sequence of floats and RGB-tuples. The floats should be increasing
    and in the interval (0,1).
    """
    seq = [(None,) * 3, 0.0] + list(seq) + [1.0, (None,) * 3]
    cdict = {'red': [], 'green': [], 'blue': []}
    for i, item in enumerate(seq):
        if isinstance(item, float):
            r1, g1, b1 = seq[i - 1]
            r2, g2, b2 = seq[i + 1]
            cdict['red'].append([item, r1, r2])
            cdict['green'].append([item, g1, g2])
            cdict['blue'].append([item, b1, b2])
    return mcolors.LinearSegmentedColormap('CustomMap', cdict)


def diverge_map(low=(239/255., 65/255., 50/255.), high=(39/255., 184/255., 148/255.)):
    """
   http://stackoverflow.com/questions/16834861/create-own-colormap-using-matplotlib-and-plot-color-scale
    low and high are colors that will be used for the two
    ends of the spectrum. they can be either color strings
    or rgb color tuples
    """
    c = mcolors.ColorConverter().to_rgb
    if isinstance(low, basestring): low = c(low)
    if isinstance(high, basestring): high = c(high)
    return make_colormap([low, c('white'), 0.5, c('white'), high])


def type_sorted_wiring(wd, confidence_lvl=0.3, binary=False, max_syn_size=0.4,
                       syn_only=True, big_entries=True):
    """
    http://stackoverflow.com/questions/16834861/create-own-colormap-using-matplotlib-and-plot-color-scale
    Calculate wiring of consensus skeletons sorted by type classification
    :return:
    """
    supp = ""
    skeleton_ids, skeleton_feats = load_celltype_feats(wd + '/celltypes/')
    skeleton_ids2, skel_type_probas = load_celltype_probas(wd + '/celltypes/')
    assert np.all(np.equal(skeleton_ids, skeleton_ids2)), "Skeleton ordering wrong for"\
                                                  "probabilities and features."
    bool_arr = np.zeros(len(skeleton_ids))
    # load loo results of evaluation
    cell_type_pred_dict = load_pkl2obj(wd + '/celltypes/'
                                            'loo_cell_pred_dict_novel.pkl')
    # remove all skeletons under confidence level
    for k, probas in enumerate(skel_type_probas):
        if np.max(probas) > confidence_lvl:
            bool_arr[k] = 1
    bool_arr = bool_arr.astype(np.bool)
    skeleton_ids = skeleton_ids[bool_arr]
    print "%d/%d are under confidence level %0.2f and being removed." % \
          (np.sum(~bool_arr), len(skeleton_ids2), confidence_lvl)
    # remove identical skeletons
    ident_cnt = 0
    skeleton_ids = skeleton_ids.tolist()
    for skel_id in skeleton_ids:
        if skel_id in [497, 474, 307, 366, 71, 385, 434, 503, 521, 285, 546,
                       158, 604]:
            skeleton_ids.remove(skel_id)
            ident_cnt += 1
    skeleton_ids = arr(skeleton_ids)
    print "Removed %d skeletons because of similarity." % ident_cnt

    # create matrix
    if syn_only:
        syn_props = load_pkl2obj('/lustre/sdorkenw/synapse_matrices/'
                                 'phil_dict.pkl')
        area_key = 'sizes_area'
        total_area_key = 'total_size_area'
        syn_pred_key = 'syn_types_pred_maj'
    else:
        syn_props = load_pkl2obj('/lustre/sdorkenw/synapse_matrices/'
                                 'phil_dict_all.pkl')
        area_key = 'cs_area'
        total_area_key = 'total_cs_area'
        syn_pred_key = 'syn_types_pred'
    dendrite_ids = set()
    pure_dendrite_ids = set()
    axon_ids = set()
    pure_axon_ids = set()
    dendrite_multiple_syns_ids = set()
    axon_multiple_syns_ids = set()
    axon_axon_ids = set()
    axon_axon_pairs = []
    for pair_name, pair in syn_props.iteritems():
        # if pair[total_area_key] != 0:
        skel_id1, skel_id2 = re.findall('(\d+)_(\d+)', pair_name)[0]
        skel_id1 = int(skel_id1)
        skel_id2 = int(skel_id2)
        if skel_id1 not in skeleton_ids or skel_id2 not in skeleton_ids:
            continue
        axon_ids.add(skel_id1)
        dendrite_ids.add(skel_id2)
        pure_axon_ids.add(skel_id1)
        pure_dendrite_ids.add(skel_id2)
        if len(pair[area_key]) > 1:
            dendrite_multiple_syns_ids.add(skel_id2)
            axon_multiple_syns_ids.add(skel_id1)
        if np.any(np.array(pair['partner_axoness']) == 1):
            axon_axon_ids.add(skel_id1)
            axon_axon_ids.add(skel_id2)
            axon_axon_pairs.append((skel_id1, skel_id2))
    all_used_ids = set()
    all_used_ids.update(axon_axon_ids)
    all_used_ids.update(axon_ids)
    all_used_ids.update(dendrite_ids)
    print "%d/%d cells have no connection between each other." %\
          (len(skeleton_ids) - len(all_used_ids), len(skeleton_ids))
    print "Using %d unique cells in wiring." % len(all_used_ids)
    axon_axon_ids = np.array(list(axon_axon_ids))
    axon_ids = np.array(list(axon_ids))
    pure_axon_ids = np.array(list(axon_ids))
    dendrite_ids = np.array(list(dendrite_ids))
    pure_dendrite_ids = np.array(list(dendrite_ids))
    axon_multiple_syns_ids = np.array(list(axon_multiple_syns_ids))
    dendrite_multiple_syns_ids = np.array(list(dendrite_multiple_syns_ids))

    # sort dendrites, axons using its type prediction. order is determined by
    # dictionaries get_id_dict_from_skel_ids
    dendrite_pred = np.array([cell_type_pred_dict[den_id] for den_id in
                              dendrite_ids])
    type_sorted_ixs = np.argsort(dendrite_pred, kind='mergesort')
    dendrite_pred = dendrite_pred[type_sorted_ixs]
    dendrite_ids = dendrite_ids[type_sorted_ixs]
    print "GP axons:", dendrite_ids[dendrite_pred==2]
    print "Ranges for dendrites[%d]: %s" % (len(dendrite_ids),
                                            class_ranges(dendrite_pred))

    pure_dendrite_pred = np.array([cell_type_pred_dict[den_id] for den_id in
                              pure_dendrite_ids])
    type_sorted_ixs = np.argsort(pure_dendrite_pred, kind='mergesort')
    pure_dendrite_pred = pure_dendrite_pred[type_sorted_ixs]
    pure_dendrite_ids = pure_dendrite_ids[type_sorted_ixs]
    print "Ranges for dendrites[%d]: %s" % (len(pure_dendrite_ids),
                                            class_ranges(pure_dendrite_pred))

    axon_pred = np.array([cell_type_pred_dict[den_id] for den_id in
                          axon_ids])
    type_sorted_ixs = np.argsort(axon_pred, kind='mergesort')
    axon_pred = axon_pred[type_sorted_ixs]
    axon_ids = axon_ids[type_sorted_ixs]
    print "Ranges for axons[%d]: %s" % (len(axon_pred), class_ranges(axon_pred))

    pure_axon_pred = np.array([cell_type_pred_dict[den_id] for den_id in
                          pure_axon_ids])
    type_sorted_ixs = np.argsort(pure_axon_pred, kind='mergesort')
    pure_axon_pred = pure_axon_pred[type_sorted_ixs]
    pure_axon_ids = pure_axon_ids[type_sorted_ixs]
    print "Ranges for axons[%d]: %s" % (len(pure_axon_ids),
                                        class_ranges(pure_axon_pred))

    ax_ax_pred = np.array([cell_type_pred_dict[ax_id] for ax_id in
                           axon_axon_ids])
    type_sorted_ixs = np.argsort(ax_ax_pred, kind='mergesort')
    ax_ax_pred = ax_ax_pred[type_sorted_ixs]
    axon_axon_ids = axon_axon_ids[type_sorted_ixs]
    print "Ranges for axons (ax-ax)[%d]: %s" % (len(ax_ax_pred),
                                                class_ranges(ax_ax_pred))

    ax_multi_syn_pred = np.array([cell_type_pred_dict[mult_syn_skel_id] for
                           mult_syn_skel_id in axon_multiple_syns_ids])
    type_sorted_ixs = np.argsort(ax_multi_syn_pred, kind='mergesort')
    ax_multi_syn_pred = ax_multi_syn_pred[type_sorted_ixs]
    axon_multiple_syns_ids = axon_multiple_syns_ids[type_sorted_ixs]
    print "Ranges for axons (multi-syn)[%d]: %s" % (len(ax_multi_syn_pred),
                                                class_ranges(ax_multi_syn_pred))

    den_multi_syn_pred = np.array([cell_type_pred_dict[mult_syn_skel_id] for
                           mult_syn_skel_id in dendrite_multiple_syns_ids])
    type_sorted_ixs = np.argsort(den_multi_syn_pred, kind='mergesort')
    den_multi_syn_pred = den_multi_syn_pred[type_sorted_ixs]
    dendrite_multiple_syns_ids = dendrite_multiple_syns_ids[type_sorted_ixs]
    print "Ranges for dendrites (multi-syn)[%d]: %s" % (len(den_multi_syn_pred),
                                                class_ranges(den_multi_syn_pred))

    den_id_dict, rev_den_id_dict = get_id_dict_from_skel_ids(dendrite_ids)
    ax_id_dict, rev_ax_id_dict = get_id_dict_from_skel_ids(axon_ids)

    # build reduced matrix
    wiring = np.zeros((len(dendrite_ids), len(axon_ids), 3), dtype=np.float)
    wiring_multiple_syns = np.zeros((len(dendrite_ids), len(axon_ids), 3),
                                    dtype=np.float)
    cum_wiring = np.zeros((4, 4, 3))
    cum_wiring_axon = np.zeros((4, 4, 3))
    wiring_axoness = np.zeros((len(dendrite_ids), len(axon_ids), 3),
                              dtype=np.float)
    for pair_name, pair in syn_props.iteritems():
        if pair[total_area_key] != 0:
            synapse_type = cell_classification(pair[syn_pred_key])
            skel_id1, skel_id2 = re.findall('(\d+)_(\d+)', pair_name)[0]
            skel_id1 = int(skel_id1)
            skel_id2 = int(skel_id2)
            if skel_id1 not in skeleton_ids or skel_id2 not in skeleton_ids:
                continue
            dendrite_pos = den_id_dict[skel_id2]
            axon_pos = ax_id_dict[skel_id1]
            cum_den_pos = cell_type_pred_dict[skel_id2]
            cum_ax_pos = cell_type_pred_dict[skel_id1]
            if np.any(np.array(pair['partner_axoness']) == 1):
                indiv_syn_sizes = np.array(pair[area_key])
                indiv_syn_axoness = np.array(pair['partner_axoness']) == 1
                axon_axon_syn_size = indiv_syn_sizes[indiv_syn_axoness]
                pair[area_key] = indiv_syn_sizes[~indiv_syn_axoness]
                pair[total_area_key] = np.sum(pair[area_key])
                y_axon_axon = np.sum(axon_axon_syn_size)
                y_axon_axon_display = np.min((y_axon_axon, max_syn_size))
                if binary:
                    y_axon_axon = 1.
                    y_axon_axon_display = 1.
                if synapse_type == 0:
                    y_entry = np.array([0, y_axon_axon, 0])
                    cum_wiring_axon[cum_den_pos, cum_ax_pos] += y_entry
                    y_entry = np.array([0, y_axon_axon_display, 0])
                else:
                    y_entry = np.array([0, 0, y_axon_axon])
                    cum_wiring_axon[cum_den_pos, cum_ax_pos] += y_entry
                    y_entry = np.array([0, 0, y_axon_axon_display])
                wiring_axoness[dendrite_pos, axon_pos] = y_entry
                if pair[total_area_key] == 0:
                    continue
            y = pair[total_area_key]
            y_display = np.min((y, max_syn_size))
            if len(pair[area_key]) > 1:
                if synapse_type == 0:
                    y_entry = np.array([0, y_display, 0])
                else:
                    y_entry = np.array([0, 0, y_display])
                wiring_multiple_syns[dendrite_pos, axon_pos] = y_entry
            if binary:
                y = 1.
                y_display = 1.
            if synapse_type == 0:
                y_entry = np.array([0, y, 0])
                cum_wiring[cum_den_pos, cum_ax_pos] += y_entry
                y_entry = np.array([0, y_display, 0])
            else:
                y_entry = np.array([0, 0, y])
                cum_wiring[cum_den_pos, cum_ax_pos] += y_entry
                y_entry = np.array([0, 0, y_display])
            wiring[dendrite_pos, axon_pos] = y_entry
    nb_axon_axon_syn = np.sum(wiring_axoness != 0)
    nb_syn = np.sum(wiring != 0)
    max_val = [np.max(wiring[..., 1]), np.max(wiring[..., 2])]
    max_val_axon_axon = [np.max(wiring_axoness[..., 1]),
                         np.max(wiring_axoness[..., 2])]
    ax_borders = class_ranges(axon_pred)[1:-1]
    den_borders = class_ranges(dendrite_pred)[1:-1]
    maj_vote = get_cell_majority_synsign(cum_wiring)
    maj_vote_axoness = get_cell_majority_synsign(cum_wiring_axon)
    print "Proportion axon-axonic:", nb_axon_axon_syn / float(nb_axon_axon_syn+nb_syn)
    print "Cum Wiring:", cum_wiring

    # normalize each channel
    if not binary:
        wiring[:, :, 1] /= max_val[0]
        wiring[:, :, 2] /= max_val[1]
        wiring_axoness[:, :, 1] /= max_val_axon_axon[0]
        wiring_axoness[:, :, 2] /= max_val_axon_axon[1]
        wiring_multiple_syns[:, :, 1] /= max_val[0]
        wiring_multiple_syns[:, :, 2] /= max_val[1]
    max_val_sym = 0.2
    # # get max MSN-> MSN:
    print "MSN->MSN"
    entry_1 = ax_id_dict[382] # ax_borders[0] + 75 #(ax_borders[0]+max_entry[0])[0]
    entry_2 = ax_id_dict[164] #ax_borders[2] + 6 #(ax_borders[2]+max_entry[1])[0]
    print rev_ax_id_dict[entry_2], cell_type_pred_dict[rev_ax_id_dict[entry_2]]
    print rev_ax_id_dict[entry_1], cell_type_pred_dict[rev_ax_id_dict[entry_1]]
    print "Synapse size:", wiring[entry_1, entry_2]
    msn_msn_row = entry_2
    msn_msn_col = entry_1
    # # get max int-> MSN:
    print "Int->MSN"
    entry_1 = ax_id_dict[371] # ax_borders[0] + 75 #(ax_borders[0]+max_entry[0])[0]
    entry_2 = ax_id_dict[472] #ax_borders[2] + 6 #(ax_borders[2]+max_entry[1])[0]
    print rev_ax_id_dict[entry_2], cell_type_pred_dict[rev_ax_id_dict[entry_2]]
    print rev_ax_id_dict[entry_1], cell_type_pred_dict[rev_ax_id_dict[entry_1]]
    print "Synapse size:", wiring[entry_1, entry_2]
    int_row = entry_2
    int_col = entry_1
    # # get max MSN->gp:
    print "MSN->GP"
    entry_1 = ax_id_dict[578] #[1]ax_borders[1] + 3#190 #(max_entry[0])[0]
    entry_2 = ax_id_dict[1] #ax_borders[0] + 93#371 #(max_entry[1])[0]
    print rev_ax_id_dict[entry_2], cell_type_pred_dict[rev_ax_id_dict[entry_2]]
    print rev_ax_id_dict[entry_1], cell_type_pred_dict[rev_ax_id_dict[entry_1]]
    print "Synapse size:", wiring[entry_1, entry_2]
    msn_gp_row = entry_2
    msn_gp_col = entry_1
    # # Get rows of GP and MSN cell, close up:
    gp_row = ax_id_dict[241]
    msn_row = ax_id_dict[31]
    gp_col = ax_id_dict[190]
    msn_col = ax_id_dict[496]
    get_close_up(wiring[:, (msn_row, gp_row, int_row, msn_gp_row, msn_msn_row)],
                 den_borders, [gp_col, msn_col, int_col, msn_gp_col, msn_msn_col])
    # print "Wrote clouse up of gp in row %d and msn in row %d." % (gp_row, msn_row)
    print "Found %d synapses." % np.sum(wiring != 0)
    if not syn_only:
        supp += '_CS'
        plot_wiring_cs(wiring, den_borders, ax_borders, max_val, confidence_lvl,
                    binary, add_fname=supp)
        plot_wiring_cs(wiring_axoness, den_borders, ax_borders, max_val_axon_axon,
                    confidence_lvl, binary, add_fname=supp+'_axon_axon')

        plot_wiring_cum_cs(cum_wiring, class_ranges(pure_dendrite_pred),
                        class_ranges(pure_axon_pred), confidence_lvl, binary,
                        add_fname=supp)

        plot_wiring_cum_cs(cum_wiring_axon, class_ranges(ax_ax_pred),
                        class_ranges(ax_ax_pred), confidence_lvl, binary,
                        add_fname=supp+'_axon_axon')

        plot_wiring_cs(wiring_multiple_syns, den_borders, ax_borders, max_val,
                    confidence_lvl, binary, add_fname=supp+'_multiple_syns')
    else:
        supp += ''
        plot_wiring(wiring, den_borders, ax_borders, max_val, confidence_lvl,
                    binary, add_fname=supp, big_entries=big_entries,
                    maj_vote=maj_vote)

        plot_wiring(wiring_axoness, den_borders, ax_borders, max_val_axon_axon,
                    confidence_lvl, binary, add_fname=supp+'_axon_axon',
                    big_entries=big_entries, maj_vote=maj_vote_axoness)

        plot_wiring_cum(cum_wiring, class_ranges(dendrite_pred),
                        class_ranges(axon_pred), confidence_lvl, binary,
                        add_fname=supp, max_val_sym=max_val_sym,
                        maj_vote=maj_vote)

        plot_wiring(wiring_multiple_syns, den_borders, ax_borders, max_val,
                    confidence_lvl, binary, add_fname=supp+'_multiple_syns',
                    big_entries=big_entries, maj_vote=maj_vote)

        wiring[:, (msn_row, gp_row, int_row, msn_gp_row, msn_msn_row)] = 100
        plot_wiring(wiring, den_borders, ax_borders, max_val, confidence_lvl,
                    binary, add_fname='MARKER', big_entries=True,
                    maj_vote=maj_vote)
        return cum_wiring


def get_cell_majority_synsign(cum_wiring):
    cum_rows = np.sum(cum_wiring, axis=0)
    maj_vote = np.zeros((4))
    for i in range(4):
        maj_vote[i] = cum_rows[i, 2] > cum_rows[i, 1]
    return maj_vote


def get_close_up(wiring, den_borders, col_entries):
    for k, b in enumerate(den_borders):
        b += k * 1
        wiring = np.concatenate((wiring[:b, :], np.zeros((1, wiring.shape[1], 3)),
                                 wiring[b:, :]), axis=0)
    closeup = np.zeros((wiring.shape[0], len(col_entries)))
    for i in range(wiring.shape[0]):
        for j in range(wiring.shape[1]):
            if wiring[i, j, 1] != 0:
                closeup[i, j] = -wiring[i, j, 1]
            elif wiring[i, j, 2] != 0:
                closeup[i, j] = wiring[i, j, 2]
    # closeup = closeup[::-1]
    matplotlib.rcParams.update({'font.size': 14})
    fig = pp.figure()
    # Create scatter plot
    gs = gridspec.GridSpec(1, 2, width_ratios=[20, 1])
    gs.update(wspace=0.05, hspace=0.08)
    ax = pp.subplot(gs[0, 0], frameon=False)
    #dark_blue = sns.diverging_palette(133, 255, center="light", as_cmap=True)
    dark_blue = sns.diverging_palette(282., 120, s=99., l=50.,
                                      center="light", as_cmap=True)
    cax = ax.matshow(closeup.transpose(1, 0), cmap=diverge_map(),
                     extent=[0, wiring.shape[0], wiring.shape[1], 0],
                     interpolation="none")
    ax.set_xlim(0, wiring.shape[0])
    ax.set_ylim(0, wiring.shape[1])
    plt.grid(False)
    plt.axis('off')
    for k, b in enumerate(den_borders):
        b += k * 1
        plt.axvline(b+0.5, color='k', lw=0.5, snap=True, antialiased=True)
    cbar_ax = pp.subplot(gs[0, 1])
    cbar_ax.yaxis.set_ticks_position('none')
    cb = fig.colorbar(cax, cax=cbar_ax, ticks=[])
    fig.savefig('/lustre/pschuber/figures/wiring/type_wiring_closeup.png',
                dpi=600)
    plt.close()
    matplotlib.rcParams.update({'font.size': 14})
    fig = pp.figure()
    # Create scatter plot
    gs = gridspec.GridSpec(1, 2, width_ratios=[20, 1])
    gs.update(wspace=0.05, hspace=0.08)
    ax = pp.subplot(gs[0, 0], frameon=False)
    #dark_blue = sns.diverging_palette(133, 255, center="light", as_cmap=True)
    dark_blue = sns.diverging_palette(282., 120, s=99., l=50.,
                                      center="light", as_cmap=True)
    cax = ax.matshow(closeup.transpose(1, 0), cmap=diverge_map(),
                     extent=[0, wiring.shape[0], wiring.shape[1], 0],
                     interpolation="none")
    ax.set_xlim(0, wiring.shape[0])
    ax.set_ylim(0, wiring.shape[1])
    plt.grid(False)
    plt.axis('off')
    for k, b in enumerate(den_borders):
        b += k * 1
        plt.axvline(b+0.5, color='k', lw=0.5, snap=True, antialiased=True)
    for col_entry in col_entries:
        additional_cols = np.sum(col_entry > den_borders)
        plt.axvline(col_entry+0.5+additional_cols, color="0.4", lw=0.5,
                    snap=True, antialiased=True)
    cbar_ax = pp.subplot(gs[0, 1])
    cbar_ax.yaxis.set_ticks_position('none')
    cb = fig.colorbar(cax, cax=cbar_ax, ticks=[])
    fig.savefig('/lustre/pschuber/figures/wiring/type_wiring_closeup_marker.png',
                dpi=600)
    plt.close()


def get_cum_pos(den_ranges, ax_ranges, den_pos, ax_pos):
    """
    Calculates the position of synapse in cumulated matrix
    """
    den_cum_pos = 0
    ax_cum_pos = 0
    for i in range(1, len(den_ranges)):
        if (den_pos >= den_ranges[i-1]) and (den_pos < den_ranges[i]):
            den_cum_pos = i-1
    for i in range(1,  len(ax_ranges)):
        if (ax_pos >= ax_ranges[i-1]) and (ax_pos < ax_ranges[i]):
            ax_cum_pos = i-1
    return den_cum_pos, ax_cum_pos


def plot_wiring(wiring, den_borders, ax_borders, max_val, confidence_lvl,
                binary, big_entries=False, add_fname='', maj_vote=[]):
    """
    :param wiring:
    :param den_borders:
    :param ax_borders:
    :param max_val:
    :param confidence_lvl:
    :param binary:
    :param add_fname:
    :param big_entries: changes entries to 3x3 squares
    :return:
    """
    for k, b in enumerate(den_borders):
        b += k * 1
        wiring = np.concatenate((wiring[:b, :], np.zeros((1, wiring.shape[1], 3)),
                                 wiring[b:, :]), axis=0)
    for k, b in enumerate(ax_borders):
        b += k * 1
        wiring = np.concatenate((wiring[:, :b], np.zeros((wiring.shape[0], 1, 3)),
                                 wiring[:, b:]), axis=1)
    intensity_plot = np.zeros((wiring.shape[0], wiring.shape[1]))
    print "Found majority vote for cell types:", maj_vote
    ax_borders_h = arr([0, ax_borders[0], ax_borders[1], ax_borders[2], wiring.shape[1]])+arr([0, 1, 2, 3, 4])
    den_borders_h = arr([0, ax_borders[0], ax_borders[1], ax_borders[2], wiring.shape[0]])+arr([0, 1, 2, 3, 4])
    wiring *= -1
    for i in range(wiring.shape[0]):
        for j in range(wiring.shape[1]):
            den_pos, ax_pos = get_cum_pos(ax_borders_h, ax_borders_h, i, j)
            syn_sign = maj_vote[ax_pos]
            if wiring[i, j, 1] != 0:
                intensity_plot[i, j] = (-1)**syn_sign * wiring[i, j, 1]
            elif wiring[i, j, 2] != 0:
                intensity_plot[i, j] = (-1)**syn_sign * wiring[i, j, 2]
            if big_entries:
                for add_i in [-1, 0, 1]:
                    for add_j in [-1, 0, 1]:
                        den_pos_i, ax_pos_j = get_cum_pos(
                            ax_borders_h, ax_borders_h, i+add_i, j+add_j)
                        if (i+add_i >= wiring.shape[0]) or (i+add_i < 0) or\
                            (j+add_j >= wiring.shape[1]) or (j+add_j < 0) or\
                            (den_pos_i != den_pos) or (ax_pos_j != ax_pos):
                            continue
                        if wiring[i, j, 1] != 0:
                            #if intensity_plot[i+add_i, j+add_j] >= -wiring[i, j, 1]:
                                intensity_plot[i+add_i, j+add_j] = (-1)**(syn_sign+1) * wiring[i, j, 1]
                        elif wiring[i, j, 2] != 0:
                            #if intensity_plot[i+add_i, j+add_j] <= wiring[i, j, 2]:
                                intensity_plot[i+add_i, j+add_j] = (-1)**(syn_sign+1) * wiring[i, j, 2]
    if not big_entries:
        np.save('/lustre/pschuber/figures/wiring/connectivity_matrix.npy',
                intensity_plot)
    print "Plotting wiring diagram with maxval", max_val, "and supplement", add_fname
    print "Max/Min in plot:", np.min(intensity_plot), np.max(intensity_plot)
    tmp_max_val = np.zeros((2))
    tmp_max_val[1] = np.min(intensity_plot)
    tmp_max_val[0] = np.max(intensity_plot)
    matplotlib.rcParams.update({'font.size': 14})
    fig = pp.figure()
    # Create scatter plot
    gs = gridspec.GridSpec(1, 2, width_ratios=[20, 1])
    gs.update(wspace=0.05, hspace=0.08)
    ax = pp.subplot(gs[0, 0], frameon=False)
    #dark_blue = sns.diverging_palette(133, 255, center="light", as_cmap=True)
    dark_blue = sns.diverging_palette(282., 120, s=99., l=50.,
                                      center="light", as_cmap=True)

    cax = ax.matshow(-intensity_plot.transpose(1, 0), cmap=diverge_map(),
                     extent=[0, wiring.shape[0], wiring.shape[1], 0],
                     interpolation="none")
    ax.set_xlabel('Post', fontsize=18)
    ax.set_ylabel('Pre', fontsize=18)
    ax.set_xlim(0, wiring.shape[0])
    ax.set_ylim(0, wiring.shape[1])
    plt.grid(False)
    plt.axis('off')

    for k, b in enumerate(den_borders):
        b += k * 1
        plt.axvline(b+0.5, color='k', lw=0.5, snap=True, antialiased=True)
    for k, b in enumerate(ax_borders):
        b += k * 1
        plt.axhline(b+0.5, color='k', lw=0.5, snap=True, antialiased=True)

    cbar_ax = pp.subplot(gs[0, 1])
    cbar_ax.yaxis.set_ticks_position('none')
    cb = fig.colorbar(cax, cax=cbar_ax, ticks=[])#[tmp_max_val[1], 0, tmp_max_val[0]])
    plt.close()

    if not binary:
        fig.savefig('/lustre/pschuber/figures/wiring/type_wiring%s_conf'
                    'lvl%d_be%s.png' % (add_fname, int(confidence_lvl*10),
                                   str(big_entries)), dpi=600)
    else:
        fig.savefig('/lustre/pschuber/figures/wiring/type_wiring%s_conf'
            'lvl%d_be%s_binary.png' % (add_fname, int(confidence_lvl*10),
                                       str(big_entries)), dpi=600)


def plot_wiring_cum(wiring, den_borders, ax_borders, confidence_lvl, max_val,
                    binary, add_fname='', maj_vote=[]):
    # plot intensities, averaged per sector
    nb_cells_per_sector = np.zeros((4, 4))
    intensity_plot = np.zeros((4, 4))
    for i in range(4):
        for j in range(4):
            diff_den = den_borders[i+1] - den_borders[i]
            diff_ax = ax_borders[j+1] - ax_borders[j]
            nb_cells_per_sector[i, j] = diff_den * diff_ax
            if nb_cells_per_sector[i, j] != 0:
                sector_intensity = np.sum(wiring[i, j]) / nb_cells_per_sector[i, j]
            else:
                sector_intensity = 0
            syn_sign = maj_vote[j]
            if wiring[i, j, 1] > wiring[i, j, 2]:
                intensity_plot[i, j] = (-1)**(syn_sign+1) * sector_intensity
            else:
                intensity_plot[i, j] = (-1)**(syn_sign+1) * np.min((sector_intensity, 0.1))
    np.save('/lustre/pschuber/figures/wiring/cumulated_connectivity_matrix.npy',
            intensity_plot)
    print intensity_plot
    ind = np.arange(4)
    intensity_plot = intensity_plot.transpose(1, 0)[::-1]
    max_val = np.array([np.max(intensity_plot),
                        np.abs(np.min(intensity_plot))])
    row_sum = np.sum(np.sum(wiring.transpose(1, 0, 2)[::-1], axis=2), axis=1)
    col_sum = np.sum(np.sum(wiring.transpose(1, 0, 2)[::-1], axis=2), axis=0)
    # for i in range(4):
    #     if row_sum[i] != 0:
    #         intensity_plot[i] /= row_sum[i]
    # intensity_plot[:, :, 1] = intensity_plot[:, :, 1] / max_val[0]
    # intensity_plot[:, :, 2] = intensity_plot[:, :, 2] / max_val[1]
    max_val_tmp = np.array([np.max(intensity_plot),
                        np.abs(np.min(intensity_plot))])
    intensity_plot[intensity_plot < 0] /= max_val_tmp[1]
    intensity_plot[intensity_plot > 0] /= max_val_tmp[0]
    print "Plotting cumulative matrix with supplement", add_fname
    print "Max/Min in plot:", np.min(intensity_plot), np.max(intensity_plot)
    print max_val
    matplotlib.rcParams.update({'font.size': 14})
    fig = pp.figure()
    # Create scatter plot
    gs = gridspec.GridSpec(2, 3, width_ratios=[10, 1, 0.5], height_ratios=[1, 10])
    gs.update(wspace=0.05, hspace=0.08)
    ax = pp.subplot(gs[1, 0], frameon=False)
    #dark_blue = sns.diverging_palette(133, 255, center="light", as_cmap=True)
    dark_blue = sns.diverging_palette(282., 120., s=99., l=50.,
                                      center="light", as_cmap=True)
    cax = ax.matshow(intensity_plot, cmap=diverge_map(), extent=[0, 4, 0, 4])
    ax.grid(color='k', linestyle='-')
    cbar_ax = pp.subplot(gs[1, 2])
    cbar_ax.yaxis.set_ticks_position('none')
    cb = fig.colorbar(cax, cax=cbar_ax, ticks=[])#[-1, 0, 1])
    # cb.ax.set_yticklabels(['         Asym[%0.4f]' % max_val[1], '0',
    #                        'Sym[%0.4f]         ' % max_val[0]], rotation=90)
    # if not binary:
    #     cb.set_label(u'Average Area of Synaptic Junctions [µm$^2$]')
    # else:
    #     cb.set_label(u'Average Number of Synaptic Junctions')
    axr = pp.subplot(gs[1, 1], sharey=ax, yticks=[],
                     xticks=[],#[0, max(row_sum)],
                     frameon=False,
                     xlim=(np.min(row_sum), np.max(row_sum)), ylim=(0, 4))
    axr.tick_params(axis='x', which='major', right="off", top="off", left="off",
                    pad=10, bottom="off", labelsize=12, direction='out',
                    length=4, width=1)
    axr.spines['top'].set_visible(False)
    axr.spines['right'].set_visible(False)
    axr.spines['left'].set_visible(False)
    axr.spines['bottom'].set_visible(False)
    axr.get_xaxis().tick_bottom()
    axr.get_yaxis().tick_left()
    axr.barh(ind, row_sum[::-1], 1, color='0.6', linewidth=0)
    axt = pp.subplot(gs[0, 0], sharex=ax, xticks=[],
                     yticks=[],#[0, max(col_sum)],
                     frameon=False, xlim=(0, 4), ylim=(np.min(col_sum),
                                                       np.max(col_sum)))
    axt.tick_params(axis='y', which='major', right="off", bottom="off", top="off",
                    left="off", pad=10, labelsize=12, direction='out', length=4,
                    width=1)
    axr.spines['top'].set_visible(False)
    axr.spines['right'].set_visible(False)
    axr.spines['left'].set_visible(False)
    axr.spines['bottom'].set_visible(False)
    axt.get_xaxis().tick_bottom()
    axt.get_yaxis().tick_left()
    axt.bar(ind, col_sum, 1, color='0.6', linewidth=0)
    # plt.show(block=False)
    plt.close()
    if not binary:
        fig.savefig('/lustre/pschuber/figures/wiring/type_wiring_cum%s_conf'
                    'lvl%d.png' % (add_fname, int(confidence_lvl*10)), dpi=600)
    else:
        fig.savefig('/lustre/pschuber/figures/wiring/type_wiring_cum%s_conf'
            'lvl%d_binary.png' % (add_fname, int(confidence_lvl*10)), dpi=600)


def type_sorted_wiring_cs(wd, confidence_lvl=0.8, binary=False,
                          max_syn_size=0.2):
    """
    Calculate wiring of consensus skeletons sorted by type classification
    :return:
    """
    skel_ids, skeleton_feats = load_celltype_feats(wd + '/celltypes/')
    skel_ids2, skel_type_probas = load_celltype_probas(wd + '/celltypes/')
    assert np.all(np.equal(skel_ids, skel_ids2)), "Skeleton ordering wrong for"\
                                                  "probabilities and features."
    bool_arr = np.zeros(len(skel_ids))
    cell_type_pred_dict = {}
    for k, skel_id in enumerate(skel_ids):
        cell_type_pred_dict[skel_id] = np.argmax(skel_type_probas[k])
    # load loo results of evaluation
    proba_fname = wd+'/res/loo_proba_rf_2labels_False_pca' \
                     '_False_evenlabels_False.npy'
    probas = np.load(proba_fname)
    # get corresponding skeleton ids
    _, _, help_skel_ids = load_celltype_gt()
    # rewrite "prediction" of samples which are in trainings set with loo-proba
    for k, skel_id in enumerate(help_skel_ids):
        cell_type_pred_dict[skel_id] = np.argmax(probas[k])
    write_obj2pkl(cell_type_pred_dict, wd + '/synapse_matrices/'
                                            'cell_pred_dict.pkl')

    # remove all skeletons under confidence level
    for k, probas in enumerate(skel_type_probas):
        if np.max(probas) > confidence_lvl:
            bool_arr[k] = 1
    bool_arr = bool_arr.astype(np.bool)
    skeleton_ids = skel_ids[bool_arr]
    print "%d/%d are under confidence level %0.2f and being removed." % \
          (np.sum(~bool_arr), len(skel_ids), confidence_lvl)

    # create matrix
    syn_props = load_pkl2obj(wd + '/synapse_matrices/phil_dict_no_'
                                  'exclusion_all.pkl')
    area_key = 'cs_area'
    total_area_key = 'total_cs_area'
    dendrite_ids = set()
    axon_ids = set()
    for pair_name, pair in syn_props.iteritems():
        # if pair[total_area_key] != 0:
        skel_id1, skel_id2 = re.findall('(\d+)_(\d+)', pair_name)[0]
        skel_id1 = int(skel_id1)
        skel_id2 = int(skel_id2)
        if skel_id1 not in skeleton_ids or skel_id2 not in skeleton_ids:
            continue
        axon_ids.add(skel_id1)
        dendrite_ids.add(skel_id2)

    all_used_ids = set()
    all_used_ids.update(axon_ids)
    all_used_ids.update(dendrite_ids)
    print "%d/%d cells have no connection between each other." %\
          (len(skeleton_ids) - len(all_used_ids), len(skeleton_ids))
    print "Using %d unique cells in wiring." % len(all_used_ids)
    axon_ids = np.array(list(axon_ids))
    dendrite_ids = np.array(list(dendrite_ids))

    # sort dendrites, axons using its type prediction. order is determined by
    # dictionaries get_id_dict_from_skel_ids
    dendrite_pred = np.array([cell_type_pred_dict[den_id] for den_id in
                              dendrite_ids])
    type_sorted_ixs = np.argsort(dendrite_pred, kind='mergesort')
    dendrite_pred = dendrite_pred[type_sorted_ixs]
    dendrite_ids = dendrite_ids[type_sorted_ixs]
    print "GP axons:", dendrite_ids[dendrite_pred==2]
    print "Ranges for dendrites[%d]: %s" % (len(dendrite_ids),
                                            class_ranges(dendrite_pred))

    axon_pred = np.array([cell_type_pred_dict[den_id] for den_id in axon_ids])
    type_sorted_ixs = np.argsort(axon_pred, kind='mergesort')
    axon_pred = axon_pred[type_sorted_ixs]
    axon_ids = axon_ids[type_sorted_ixs]
    print "GP axons:", axon_ids[axon_pred==2]
    print "Ranges for axons[%d]: %s" % (len(axon_pred), class_ranges(axon_pred))

    den_id_dict, rev_den_id_dict = get_id_dict_from_skel_ids(dendrite_ids)
    ax_id_dict, rev_ax_id_dict = get_id_dict_from_skel_ids(axon_ids)

    wiring = np.zeros((len(dendrite_ids), len(axon_ids), 1), dtype=np.float)
    cum_wiring = np.zeros((4, 4))
    for pair_name, pair in syn_props.iteritems():
        if pair[total_area_key] != 0:
            skel_id1, skel_id2 = re.findall('(\d+)_(\d+)', pair_name)[0]
            skel_id1 = int(skel_id1)
            skel_id2 = int(skel_id2)
            if skel_id1 not in skeleton_ids or skel_id2 not in skeleton_ids:
                continue
            dendrite_pos = den_id_dict[skel_id2]
            axon_pos = ax_id_dict[skel_id1]
            cum_den_pos = cell_type_pred_dict[skel_id2]
            cum_ax_pos = cell_type_pred_dict[skel_id1]
            y = pair[total_area_key]
            if binary:
                y = 1.
            wiring[dendrite_pos, axon_pos] = np.min((y, max_syn_size))
            cum_wiring[cum_den_pos, cum_ax_pos] += y
    ax_borders = class_ranges(axon_pred)[1:-1]
    den_borders = class_ranges(dendrite_pred)[1:-1]
    supp = '_CS'
    plot_wiring_cs(wiring, den_borders, ax_borders, confidence_lvl,
                binary, add_fname=supp)

    plot_wiring_cum_cs(cum_wiring, class_ranges(dendrite_pred),
                    class_ranges(axon_pred), confidence_lvl, binary,
                    add_fname=supp)


def plot_wiring_cs(wiring, den_borders, ax_borders, confidence_lvl, max_val,
                binary, add_fname='_CS'):
    fig = plt.figure()
    ax = plt.gca()
    max_val = np.max(wiring)
    for k, b in enumerate(den_borders):
        b += k * 1
        wiring = np.concatenate((wiring[:b, :], np.ones((1, wiring.shape[1], 1)),
                                 wiring[b:, :]), axis=0)
    for k, b in enumerate(ax_borders):
        b += k * 1
        wiring = np.concatenate((wiring[:, :b], np.ones((wiring.shape[0], 1, 1)),
                                 wiring[:, b:]), axis=1)
    im = ax.matshow(np.max(wiring.transpose(1, 0, 2), axis=2), interpolation="none",
                   extent=[0, wiring.shape[0], wiring.shape[1], 0], cmap='gray')
    ax.set_xlabel('Post', fontsize=18)
    ax.set_ylabel('Pre', fontsize=18)
    ax.set_xlim(0, wiring.shape[0])
    ax.set_ylim(0, wiring.shape[1])
    plt.grid(False)
    plt.axis('off')
    divider = make_axes_locatable(ax)
    cax = divider.append_axes("right", size="5%", pad=0.1)
    a = np.array([[0, 1]])
    plt.figure()
    img = plt.imshow(a, cmap='gray')
    plt.gca().set_visible(False)
    cb = plt.colorbar(cax=cax, ticks=[0, 1])
    if not binary:
        cb.ax.set_yticklabels(['0', "%0.3g+" % max_val], rotation=90)
        cb.set_label(u'Area of Synaptic Junctions [µm$^2$]')
    else:
        cb.ax.set_yticklabels(['0', '1'], rotation=90)
        cb.set_label(u'Synaptic Junction')
    plt.close()
    if not binary:
        fig.savefig('/lustre/pschuber/figures/wiring/type_wiring%s_conf'
                    'lvl%d.png' % (add_fname, int(confidence_lvl*10)), dpi=600)
    else:
        fig.savefig('/lustre/pschuber/figures/wiring/type_wiring%s_conf'
            'lvl%d_binary.png' % (add_fname, int(confidence_lvl*10)), dpi=600)


def plot_wiring_cum_cs(wiring, den_borders, ax_borders, confidence_lvl,
                       binary, add_fname=''):
    # plot cumulated wiring

    # plot intensities, averaged per sector
    nb_cells_per_sector = np.zeros((4, 4))
    intensity_plot = np.zeros((4, 4))
    for i in range(4):
        for j in range(4):
            diff_den = den_borders[i+1] - den_borders[i]
            diff_ax = ax_borders[j+1] - ax_borders[j]
            nb_cells_per_sector[i, j] = diff_den * diff_ax
            if nb_cells_per_sector[i, j] != 0:
                sector_intensity = np.sum(wiring[i, j]) / nb_cells_per_sector[i, j]
            else:
                sector_intensity = 0
            intensity_plot[i, j] = sector_intensity
    ind = np.arange(4)
    intensity_plot = intensity_plot.transpose(1, 0)[::-1]
    wiring = wiring.transpose(1, 0)[::-1]
    intensity_plot[intensity_plot > 1.0] = 1.0
    max_val = np.max(intensity_plot)
    row_sum = np.sum(wiring, axis=1)
    col_sum = np.sum(wiring, axis=0)
    intensity_plot = (intensity_plot - intensity_plot.min())/\
                     np.max((intensity_plot.max() - intensity_plot.min()))

    print row_sum
    print col_sum
    from matplotlib import pyplot as pp
    from matplotlib import gridspec
    matplotlib.rcParams.update({'font.size': 14})
    fig = pp.figure()
    # Create scatter plot
    gs = gridspec.GridSpec(2, 3, width_ratios=[10, 1, 0.5], height_ratios=[1, 10])
    gs.update(wspace=0.05, hspace=0.08)
    ax = pp.subplot(gs[1, 0], frameon=False)
    cax = ax.matshow(intensity_plot, cmap='gray_r', extent=[0, 4, 0, 4])
    ax.grid(color='k', linestyle='-')
    cbar_ax = pp.subplot(gs[1, 2])
    cbar_ax.yaxis.set_ticks_position('left')
    cb = fig.colorbar(cax, cax=cbar_ax, ticks=[0, 1])
    cb.ax.set_yticklabels(['0', '%0.4f' % max_val], rotation=90)
    if not binary:
        cb.set_label(u'Average Area of Contact Sites [µm$^2$]')
    else:
        cb.set_label(u'Average Number of Contact Sites')

    axr = pp.subplot(gs[1, 1], sharey=ax, yticks=[],
                     xticks=[0, max(row_sum)], frameon=True,
                     xlim=(np.min(row_sum), np.max(row_sum)), ylim=(0, 4))
    axr.tick_params(axis='x', which='major', right="off", top="off", pad=10,
                    labelsize=12, direction='out', length=4, width=1)
    axr.spines['top'].set_visible(False)
    axr.spines['right'].set_visible(False)
    axr.get_xaxis().tick_bottom()
    axr.get_yaxis().tick_left()
    axr.barh(ind, row_sum[::-1], 1, color='0.6', linewidth=0)
    axt = pp.subplot(gs[0, 0], sharex=ax, xticks=[],
                     yticks=[0, max(col_sum)],
                     frameon=True, xlim=(0, 4), ylim=(np.min(col_sum),
                                                       np.max(col_sum)))
    axt.tick_params(axis='y', which='major', right="off", bottom="off", pad=10,
                    labelsize=12, direction='out', length=4, width=1)
    axt.spines['top'].set_visible(False)
    axt.spines['right'].set_visible(False)
    axt.get_xaxis().tick_bottom()
    axt.get_yaxis().tick_left()
    axt.bar(ind, col_sum, 1, color='0.6', linewidth=0)
    plt.show(block=False)
    if not binary:
        fig.savefig('/lustre/pschuber/figures/wiring/type_wiring_cum%s_conf'
                    'lvl%d.png' % (add_fname, int(confidence_lvl*10)), dpi=600)
    else:
        fig.savefig('/lustre/pschuber/figures/wiring/type_wiring_cum%s_conf'
            'lvl%d_binary.png' % (add_fname, int(confidence_lvl*10)), dpi=600)


def class_ranges(pred_arr):
    if len(pred_arr) == 0:
        return np.array([0, 0, 0, 0, 0])
    class1 = np.argmax(pred_arr == 1)
    class2 = np.max((class1, np.argmax(pred_arr == 2)))
    class3 = np.max((class2, np.argmax(pred_arr == 3)))
    return np.array([0, class1, class2, class3, len(pred_arr)])


def get_cs_of_mapped_skel(skel_path):
    """
    Gather all contact site of mapped skeleton at skel_path and writes .nml to
    */nml_obj/cs_of_skel*.nml
    :param skel_path: str Path to k.zip
    """
    dir, filename = os.path.split(skel_path)
    skel_id = re.findall('iter_\d+_(\d+)-', filename)[0]
    contact_sites_of_skel = newskeleton()
    contact_sites_of_skel.scaling = [9, 9, 20]
    paths = get_filepaths_from_dir(dir+'/contact_sites/', ending='skel_'+skel_id)
    paths += get_filepaths_from_dir(dir+'/contact_sites/', ending=skel_id+'.nml')
    for path in paths:
        anno = au.loadj0126NML(path)[0]
        contact_sites_of_skel.add_annotation(anno)
    print "Writing file" + dir + '/cs_of_skel%s.nml' % skel_id
    contact_sites_of_skel.toNml(dir+'/cs_of_skel%s.nml' % skel_id)
    return