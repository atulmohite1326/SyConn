# Mapping of cellular organelles
`SegmentationObjects` are mapped to supervoxel (`sv`) `SegmentationObjects`. Each `SuperSegmentationObject` then aggregates the `SegmentationObjects` from its supervoxels.
The relevant code for the object mapping is in `syconn.proc.sd_proc` and `syconn.proc.ssd_proc`.

## Prerequisites
* SegmentationDatasets of cellular organelles (see [object mapping](object_mapping.md) and [SegmentationDataset](segmentation_datasets.md))
* Segmentation- and KnossosDataset of supervoxel segmentation (i.e. 64 bit Knossos cubes).
* [SSD](super_segmentation_datasets.md) of cellular supervoxels for the aggregation to SSVs.

## Mapping objects to supervoxels
Objects are mapped to supervoxels with

    from syconn.proc import sd_proc
    
    sd_proc.map_objects_to_sv(sd, obj_type, kd_path,
                              qsub_pe=my_qsub_pe, nb_cpus=1,
                              n_max_co_processes=200)

`sd` refers to the supervoxels `SegmentationDataset` which already owns the `SegmentationDatasets` from the other object types. `knossos_path` is the path to the `knossosdataset` containing the original segmentation.


## Aggregating mappings
<img align="right" width="200" height="200" src="./_static/mapped_cell_organelles2_3D_2855_4900_4617_28985344_sv.png">

Mappings are collected by `SuperSegmentationObjects` (see also [SSO](super_segmentation_objects.md);
illustration: mitochondria (blue), vesicle clouds (green), synaptic junctions (red)) using

    from syconn.proc import ssd_proc
    ssd_proc.aggregate_segmentation_object_mappings(ssd, obj_types, qsub_pe=my_qsub_pe)


Upon aggregation objects may overlap completely or partly with the `SuperSegmentationObject`.
Object type specific lower and upper thresholds then define which objects get mapped to the `SuperSegmentationObjects`.
 Typically, the upper threshold is only used for synapse objects.  Currently, these
 parameters need to be defined in the config file (see `config`).

    ssd_proc.apply_mapping_decisions(ssd, obj_types, qsub_pe=my_qsub_pe)

