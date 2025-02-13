from syconn.reps.super_segmentation import *
from syconn.reps.super_segmentation_helper import semseg_of_sso_nocache
from syconn.proc.ssd_assembly import init_sso_from_kzip
from syconn.handler.prediction import get_semseg_axon_model
import os
import argparse


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='SyConn example run')
    parser.add_argument('--working_dir', type=str,
                        default=os.path.expanduser("~/SyConn/example_cube1/"),
                        help='Working directory of SyConn')
    parser.add_argument('--kzip', type=str, default='',
                        help='path to kzip file which contains a cell reconstruction (see '
                             'SuperSegmentationObject().export2kzip())')
    parser.add_argument('--modelpath', type=str, default=None,
                        help='path to the model.pt file of the trained model.')
    args = parser.parse_args()

    # path to working directory of example cube - required to load pretrained models
    path_to_workingdir = os.path.expanduser(args.working_dir)

    # path to cell reconstruction k.zip
    cell_kzip_fn = os.path.abspath(os.path.expanduser(args.kzip))
    if not os.path.isfile(cell_kzip_fn):
        raise FileNotFoundError('Could not find a cell reconstruction file at the specified '
                                'location.')
    # set working directory to obtain models
    global_params.wd = path_to_workingdir

    model_p = args.modelpath

    if model_p is None:
        m = get_semseg_axon_model()
    else:
        try:
            from elektronn3.models.base import InferenceModel
        except ImportError as e:
            msg = "elektronn3 could not be imported ({}). Please see 'https://github." \
                  "com/ELEKTRONN/elektronn3' for more information.".format(e)
            raise ImportError(msg)
        m = InferenceModel(model_p)
        m._path = model_p

    # get model for compartment detection

    view_props = global_params.view_properties_semsegax
    view_props["verbose"] = True

    # load SSO instance from k.zip file
    sso = init_sso_from_kzip(cell_kzip_fn, sso_id=1)
    # run prediction and store result in new kzip
    cell_kzip_fn_axon = cell_kzip_fn[:-6] + '_axon.k.zip'
    semseg_of_sso_nocache(sso, dest_path=cell_kzip_fn_axon, model=m,
                          **view_props)

    node_preds = sso.semseg_for_coords(
        sso.skeleton['nodes'], view_props['semseg_key'],
        **global_params.map_properties_semsegax)
    sso.skeleton[view_props['semseg_key']] = node_preds
    sso.save_skeleton_to_kzip(dest_path=cell_kzip_fn_axon,
                              additional_keys=view_props['semseg_key'])
