# -*- coding: utf-8 -*-
# SyConn - Synaptic connectivity inference toolkit
#
# Copyright (c) 2016 - now
# Max Planck Institute of Neurobiology, Martinsried, Germany
# Authors: Sven Dorkenwald, Philipp Schubert, Joergen Kornfeld

import itertools
import numpy as np
from collections import Counter
from numba import jit
from scipy import spatial, ndimage
from skimage import measure
from sklearn.decomposition import PCA
from ..handler.basics import write_txt2kzip, texts2kzip, chunkify
from .image import apply_pca
try:
    from vigra.filters import boundaryDistanceTransform, gaussianSmoothing
except ImportError as e:
    print(repr(e))
from scipy.ndimage.morphology import binary_closing
import time
try:
    import vtkInterface
    __vtk_avail__ = True
except ImportError:
    __vtk_avail__ = False
from ..mp.shared_mem import start_multiprocess_obj, start_multiprocess_imap
__all__ = ["MeshObject", "get_object_mesh", "merge_meshes", "triangulation",
           "get_random_centered_coords", "write_mesh2kzip", 'write_meshes2kzip',
           "compartmentalize_mesh", 'write_ssomesh2kzip']


class MeshObject(object):
    def __init__(self, object_type, indices, vertices, normals=None,
                 color=None, bounding_box=None):
        self.object_type = object_type
        if vertices.ndim == 2 and vertices.shape[1] == 3:
            self.vertices = vertices.flatten()
        else:
            # assume flat array
            self.vertices = np.array(vertices, dtype=np.float)
        if indices.ndim == 2 and indices.shape[1] == 3:
            self.indices = indices.flatten().astype(np.uint)
        else:
            # assume flat array
            self.indices = np.array(indices, dtype=np.uint)
        if len(self.vertices) == 0:
            self.center = 0
            self.max_dist = 1
            self._normals = np.zeros((0, 3))
            return
        if bounding_box is None:
            self.center, self.max_dist = get_bounding_box(self.vertices)
        else:
            self.center = bounding_box[0]
            self.max_dist = bounding_box[1]
        self.center = self.center.astype(np.float)
        self.max_dist = self.max_dist.astype(np.float)
        vert_resh = np.array(self.vertices).reshape((len(self.vertices) // 3, 3))
        vert_resh -= np.array(self.center, dtype=self.vertices.dtype)
        vert_resh = vert_resh / np.array(self.max_dist)
        self.vertices = vert_resh.reshape(len(self.vertices))
        if normals is not None and len(normals) == 0:
            normals = None
        if normals is not None and normals.ndim == 2:
            normals = normals.reshape(len(normals)*3)
        self._normals = normals
        self._ext_color = color
        self._colors = None
        self.pca = None

    @property
    def colors(self):
        if self._ext_color is None:
            self._colors = np.ones(len(self.vertices) // 3 * 4) * 0.5
        elif np.isscalar(self._ext_color):
            self._colors = np.array(len(self.vertices) // 3 * [self._ext_color]).flatten()
        else:
            if np.ndim(self._ext_color) >= 2:
                self._ext_color = self._ext_color.squeeze()
                assert self._ext_color.shape[1] == 4,\
                    "'color' parameter has wrong shape"
                self._ext_color = self._ext_color.squeeze()
                assert self._ext_color.shape[1] == 4,\
                    "Rendering requires RGBA 'color' shape of (X, 4). Please" \
                    "add alpha channel."
                self._ext_color = self._ext_color.flatten()
            assert len(self._ext_color)/4 == len(self.vertices)/3, \
                "len(ext_color)/4 must be equal to len(vertices)/3."
            self._colors = self._ext_color
        return self._colors

    @property
    def vert_resh(self):
        vert_resh = np.array(self.vertices).reshape(-1, 3)
        return vert_resh

    @property
    def normals(self):
        if self._normals is None or len(self._normals) != len(self.vertices):
            print("Calculating normals")
            self._normals = unit_normal(self.vertices, self.indices)
        elif len(self._normals) != len(self.vertices):
            print("Calculating normals, because their shape differs from"
                  " vertices: %s (normals) vs. %s (vertices)" %
                  (str(self._normals.shape), str(self.vertices.shape)))
            self._normals = unit_normal(self.vertices, self.indices)
        return self._normals

    @property
    def normals_resh(self):
        return self.normals.reshape(-1, 3)

    def transform_external_coords(self, coords):
        """

        Parameters
        ----------
        coords : np.array

        Returns
        -------
        np.array
            transformed coordinates
        """
        if len(coords) == 0:
            return coords
        coords = np.array(coords, dtype=np.float)
        coords = coords - self.center
        coords /= self.max_dist
        return coords

    def retransform_external_coords(self, coords):
        coords = np.array(coords, dtype=np.float)
        coords *= self.max_dist
        coords += self.center
        return coords.astype(np.int)

    @property
    def bounding_box(self):
        return [self.center, self.max_dist]

    def perform_pca_rotation(self):
        """
        Rotates vertices into principal component coordinate system.
        """
        if self.pca is None:
            self.pca = PCA(n_components=3, whiten=False)
            self.pca.fit(self.vert_resh)
        self.vertices = self.pca.transform(
            self.vert_resh).reshape(len(self.vertices))

    def renormalize_vertices(self, bounding_box=None):
        """
        Renomralize, i.e. substract mean and divide by max. extent, vertices
        using either center and max. distance from self.vertices or given from
        keyword argument bounding_box.

        Parameters
        ----------
        bounding_box : tuple
            center, scale (applied as follows: self.vert_resh / scale)
        """
        if bounding_box is None:
            bounding_box = get_bounding_box(self.vertices)
        self.center, self.max_dist = bounding_box
        self.center = self.center.astype(np.float)
        self.max_dist = self.max_dist.astype(np.float)
        vert_resh = np.array(self.vertices).reshape(len(self.vertices) // 3, 3)
        vert_resh -= self.center
        vert_resh /= self.max_dist
        self.vertices = vert_resh.reshape(len(self.vertices))

    @property
    def vertices_scaled(self):
        return (self.vert_resh * self.max_dist + self.center).flatten()


def triangulation(pts, downsampling=(1, 1, 1), n_closings=0,
                  single_cc=False, decimate_mesh=0):
    """
    Calculates triangulation of point cloud or dense volume using marching cubes
    by building dense matrix (in case of a point cloud) and applying marching
    cubes.

    Parameters
    ----------
    pts : numpy.array [N, 3] or [N, M, O] (dtype: uint8, bool)
    downsampling : tuple of int
        Magnitude of downsampling, e.g. 1, 2, (..) which is applied to pts
        for each axis
    scaling : tuple
    n_closings : int
        Number of closings applied before mesh generation
    single_cc : bool
        Returns mesh of biggest connected component only
    decimate_mesh : float
        Percentage of mesh size reduction, i.e. 0.1 will leave 90% of the
        vertices

    Returns
    -------
    array, array, array
        indices [M, 3], vertices [N, 3], normals [N, 3]

    """
    assert type(downsampling) == tuple, "Downsampling has to be of type 'tuple'"
    assert (pts.ndim == 2 and pts.shape[1] == 3) or pts.ndim == 3, \
        "Point cloud used for mesh generation has wrong shape."
    if pts.ndim == 2:
        if np.max(pts) <= 1:
            raise ValueError("Currently this function only supports point clouds with coordinates >> 1.")
        offset = np.min(pts, axis=0)
        pts -= offset
        pts = (pts / downsampling).astype(np.uint32)
        # add zero boundary around object
        pts += 5
        bb = np.max(pts, axis=0) + 5
        volume = np.zeros(bb, dtype=np.float32)
        volume[pts[:, 0], pts[:, 1], pts[:, 2]] = 1
    else:
        volume = pts
        if np.any(np.array(downsampling) != 1):
            volume = measure.block_reduce(volume, downsampling, np.max)
        offset = np.array([0, 0, 0])
    # volume = multiBinaryErosion(volume, 1).astype(np.float32)
    if n_closings > 0:
        volume = binary_closing(volume, iterations=n_closings).astype(np.float32)
    if single_cc:
        labeled, nb_cc = ndimage.label(volume)
        cnt = Counter(labeled.flatten())
        l, occ = cnt.most_common(1)[0]
        volume = np.array(labeled == l, dtype=np.float32)
    dt = boundaryDistanceTransform(volume, boundary="InterpixelBoundary") #InterpixelBoundary, OuterBoundary, InnerBoundary
    dt[volume == 1] *= -1
    volume = gaussianSmoothing(dt, 1) # this works because only the relative step_size between the dimensions is interesting, therefore we can neglect shrink_fct
    if np.sum(volume < 0) == 0 or  np.sum(volume > 0) == 0:  # less smoothing
        volume = gaussianSmoothing(dt, 0.5)
    try:
        verts, ind, norm, _ = measure.marching_cubes_lewiner(volume, 0, gradient_direction="descent") # also calculates normals!
    except Exception as e:
        print(e)
        raise RuntimeError
    if pts.ndim == 2:  # account for [5, 5, 5] offset
        verts -= 5
    verts = np.array(verts) * downsampling + offset
    if decimate_mesh > 0:
        assert __vtk_avail__, "vtkInterface not installed. Please install vtkInterface." \
                              "'git clone https://github.com/akaszynski/vtkInterface.git' and 'pip install -e vtkInterface'."
        print("Currently mesh-sparsification may not preserve"
              " volume.")
        # add number of vertices in front of every face (required by vtkInterface)
        ind = np.concatenate([np.ones((len(ind), 1)).astype(np.int64) * 3, ind], axis=1)
        mesh = vtkInterface.PolyData(verts, ind.flatten()).TriFilter()
        decimated_mesh = mesh.Decimate(decimate_mesh, volume_preservation=True)
        # remove face sizes again
        ind = decimated_mesh.faces.reshape((-1, 4))[:, 1:]
        verts = decimated_mesh.points
        mo = MeshObject("", ind, verts)
        # compute normals
        norm = mo.normals.reshape((-1, 3))
    return np.array(ind, dtype=np.int), verts, norm


def get_object_mesh(obj, downsampling, n_closings, decimate_mesh=0):
    """
    Get object mesh from object voxels using marching cubes.

    Parameters
    ----------
    obj : SegmentationObject
    downsampling : tuple of int
        Magnitude of downsampling for each axis
    n_closings : int
        Number of closings before mesh generation
    decimate_mesh : float

    Returns
    -------
    array [N, 1], array [M, 1], array
        vertices, indices
    """
    if np.isscalar(obj.voxels):
        return np.zeros((0, )), np.zeros((0, ))

    indices, vertices, normals = triangulation(np.array(obj.voxel_list),
                                      downsampling=downsampling,
                                               n_closings=n_closings,
                                               decimate_mesh=decimate_mesh)
    vertices += 1  # account for knossos 1-indexing
    vertices = np.round(vertices * obj.scaling)
    assert len(vertices) == len(normals) or len(normals) == 0, \
        "Length of normals (%s) does not correspond to length of" \
        " vertices (%s)." % (str(normals.shape), str(vertices.shape))
    return indices.flatten(), vertices.flatten(), normals.flatten()


def normalize_vertices(vertices):
    """
    Rotate, center and normalize vertices.

    Parameters
    ----------
    vertices : array [N, 1]

    Returns
    -------
    array
        transformed vertices
    """
    vert_resh = vertices.reshape(len(vertices) // 3, 3)
    vert_resh = apply_pca(vert_resh)
    vert_resh -= np.median(vert_resh, axis=0)
    max_val = np.abs(vert_resh).max()
    vert_resh = vert_resh / max_val
    vertices = vert_resh.reshape(len(vertices)).astype(np.float32)
    return vertices


def calc_rot_matrices(coords, vertices, edge_lengths):
    """
    Fits a PCA to local sub-volumes in order to rotate them according to
    its main process (e.g. x-axis will be parallel to the long axis of a tube)

    Parameters
    ----------
    coords : np.array [M x 3]
    vertices : np.array [N x 3]
    edge_lengths : np.array
        spatial extent of box used for fitting pca

    Returns
    -------
    np.array [M x 16]
        Fortran flattened OpenGL rotation matrix
    """
    if not isinstance(edge_lengths, np.ndarray):
        raise TypeError
    if len(vertices) > 1e5:
        vertices = vertices[::8]
    rot_matrices = np.zeros((len(coords), 16))
    for ii, c in enumerate(coords):
        bounding_box = (c, edge_lengths)
        inlier = np.array(vertices[in_bounding_box(vertices, bounding_box)])
        rot_matrices[ii] = get_rotmatrix_from_points(inlier)
    return rot_matrices


def get_rotmatrix_from_points(points):
    """
    Fits pca to input points and returns corresponding rotation matrix, usable
    in PyOpenGL.

    Parameters
    ----------
    points : np.array

    Returns
    -------

    """
    if len(points) <= 2:
        return np.zeros((16))
    new_center = np.mean(points, axis=0)
    points -= new_center
    pca = PCA(n_components=3)
    pca.fit(points)
    rot_mat = np.zeros((4, 4))
    rot_mat[:3, :3] = pca.components_
    rot_mat[3, 3] = 1
    rot_mat = rot_mat.flatten('F')
    return rot_mat


def flag_empty_spaces(coords, vertices, edge_lengths):
    """
    Flag empty locations.

    Parameters
    ----------
    coords : np.array [M x 3]
    vertices : np.array [N x 3]
    edge_lengths : np.array
        spatial extent of bounding box to look for vertex support

    Returns
    -------
    np.array [M x 1]
        
    """
    assert isinstance(edge_lengths, np.ndarray)
    if len(vertices) > 1e6:
        vertices = vertices[::8]
    empty_spaces = np.zeros((len(coords))).astype(np.bool)
    for ii, c in enumerate(coords):
        bounding_box = (c, edge_lengths)
        inlier = np.array(vertices[in_bounding_box(vertices, bounding_box)])
        if len(inlier) == 0:
            empty_spaces[ii] = True
    return empty_spaces


def get_bounding_box(coordinates):
    """
    Calculates center of coordinates and its maximum distance in any spatial
    dimension to the most distant point.

    Parameters
    ----------
    coordinates : np.array

    Returns
    -------
    np.array, float
        center, distance
    """
    if coordinates.ndim == 2 and coordinates.shape[1] == 3:
        coord_resh = coordinates
    else:
        coord_resh = coordinates.reshape(len(coordinates) // 3, 3)
    mean = np.mean(coord_resh, axis=0)
    max_dist = np.max(np.abs(coord_resh - mean))
    return mean, max_dist


@jit
def in_bounding_box(coords, bounding_box):
    """
    Loop version with numba
    Parameters
    ----------
    coords : np.array (N x 3)
    bounding_box : tuple (np.array, np.array)
        center coordinate and edge lengths of bounding box

    Returns
    -------
    np.array of bool
        inlying coordinates are indicated as true
    """
    edge_sizes = bounding_box[1] / 2
    coords = np.array(coords) - bounding_box[0]
    inlier = np.zeros((len(coords)), dtype=np.bool)
    for i in range(len(coords)):
        x_cond = (coords[i, 0] > -edge_sizes[0]) & (coords[i, 0] < edge_sizes[0])
        y_cond = (coords[i, 1] > -edge_sizes[1]) & (coords[i, 1] < edge_sizes[1])
        z_cond = (coords[i, 2] > -edge_sizes[2]) & (coords[i, 2] < edge_sizes[2])
        inlier[i] = x_cond & y_cond & z_cond
    return inlier


@jit
def get_avg_normal(normals, indices, nbvert):
    normals_avg = np.zeros((nbvert, 3), np.float)
    for n in range(len(indices)):
        ix = indices[n]
        normals_avg[ix] += normals[n]
    return normals_avg


def unit_normal(vertices, indices):
    """
    Calculates normals per face (averaging corresponding vertex normals) and
    expands it to (averaged) normals per vertex.

    Parameters
    ----------
    vertices : np.array [N x 1]
        Flattend vertices
    indices : np.array [M x 1]
        Flattend indices

    Returns
    -------
    np.array [N x 1]
        Unit face normals per vertex
    """
    vertices = np.array(vertices, dtype=np.float)
    nbvert = len(vertices) // 3
    # get coordinate list
    vert_lst = vertices.reshape(nbvert, 3)[indices]
    # get traingles from coordinates
    triangles = vert_lst.reshape(len(vert_lst) // 3, 3, 3)
    # calculate normals of triangles
    v = triangles[:, 1] - triangles[:, 0]
    w = triangles[:, 2] - triangles[:, 0]
    normals = np.cross(v, w)
    norm = np.linalg.norm(normals, axis=1)
    normals[norm != 0, :] = normals[norm != 0, :] / norm[norm != 0, None]
    # repeat normal, s.t. len(normals) == len(vertices), i.e. every vertex nows
    # its normal (multiple normals because one vertex is part of multiple triangles
    normals = np.array(list(itertools.chain.from_iterable(itertools.repeat(x, 3) for x in normals)))
    # average normal for every vertex
    normals_avg = get_avg_normal(normals, indices, nbvert)
    return -normals_avg.astype(np.float32).reshape(nbvert*3)


def get_random_centered_coords(pts, nb, r):
    """

    Parameters
    ----------
    pts : np.array
        coordinates
    nb : int
        number of center of masses to be returned
    r : int
        radius of query_ball_point in order to get list of points for
        center of mass

    Returns
    -------
    np.array
        coordinates of randomly located center of masses in pts
    """
    tree = spatial.cKDTree(pts)
    rand_ixs = np.random.randint(0, len(pts), nb)
    close_ixs = tree.query_ball_point(pts[rand_ixs], r)
    coms = np.zeros((nb, 3))
    for i, ixs in enumerate(close_ixs):
        coms[i] = np.mean(pts[ixs], axis=0)
    return coms


def merge_meshes(ind_lst, vert_lst, nb_simplices=3):
    """
    Combine several meshes into a single one.

    Parameters
    ----------
    ind_lst : list of np.array [N, 1]
    vert_lst : list of np.array [N, 1]
    nb_simplices : int
        Number of simplices, e.g. for triangles nb_simplices=3

    Returns
    -------
    np.array, np.array
    """
    assert len(vert_lst) == len(ind_lst), "Length of indices list differs" \
                                          "from vertices list."
    all_ind = np.zeros((0, ), dtype=np.uint)
    all_vert = np.zeros((0, ))
    for i in range(len(vert_lst)):
        all_ind = np.concatenate([all_ind, ind_lst[i] +
                                  len(all_vert)/nb_simplices])
        all_vert = np.concatenate([all_vert, vert_lst[i]])
    return all_ind, all_vert


def mesh_loader(so):
    return so.mesh


def merge_someshes(sos, nb_simplices=3, nb_cpus=1, color_vals=None,
                  cmap=None, alpha=1.0):
    """
    Merge meshes of SegmentationObjects.

    Parameters
    ----------
    sos : iterable of SegmentationObject
        SegmentationObjects are used to get .mesh, N x 1
    nb_simplices : int
        Number of simplices, e.g. for triangles nb_simplices=3
    color_vals : iterable of float
        color values for every mesh, N x 4 (rgba). No normalization!
    nb_cpus : int
    cmap : matplotlib colormap
    alpha : float

    Returns
    -------
    np.array, np.array [, np.array]
        indices, vertices (scaled) [,colors]
    """
    all_ind = np.zeros((0, ), dtype=np.uint)
    all_vert = np.zeros((0, ))
    all_norm = np.zeros((0, ))
    colors = np.zeros((0, ))
    meshes = start_multiprocess_imap(mesh_loader, sos, nb_cpus=nb_cpus,
                                     show_progress=False)
    if color_vals is not None and cmap is not None:
        color_vals = color_factory(color_vals, cmap, alpha=alpha)
    for i in range(len(meshes)):
        ind, vert, norm = meshes[i]
        assert len(vert) == len(norm) or len(norm) == 0, "Length of normals " \
                                                         "and vertices differ."
        all_ind = np.concatenate([all_ind, ind + len(all_vert)/nb_simplices])
        all_vert = np.concatenate([all_vert, vert])
        all_norm = np.concatenate([all_norm, norm])
        if color_vals is not None:
            curr_color = np.array([color_vals[i]]*len(vert))
            colors = np.concatenate([colors, curr_color])
    assert len(all_vert) == len(all_norm) or len(all_norm) == 0, \
        "Length of combined normals and vertices differ."
    if color_vals is not None:
        return all_ind, all_vert, all_norm, colors
    return all_ind, all_vert, all_norm


def make_ply_string(indices, vertices, normals, rgba_color):
    """
    Creates a ply str that can be included into a .k.zip for rendering
    in KNOSSOS.

    Parameters
    ----------
    indices : iterable of indices (int)
    vertices : iterable of vertices (int)
    normals : iterable of normals (float)
    rgba_color : 4-tuple (uint8)

    Returns
    -------
    str
    """
    # create header
    if not indices.ndim == 2:
        indices = np.array(indices, dtype=np.int).reshape((-1, 3))
    if not vertices.ndim == 2:
        vertices = np.array(vertices, dtype=np.float32).reshape((-1, 3))
    if len(rgba_color) != len(vertices) and len(rgba_color) == 4:
        rgba_color = [rgba_color for i in range(len(vertices))]
    else:
        assert len(rgba_color) == len(vertices) and len(rgba_color[0]) == 4
    if type(rgba_color) is list:
        print("WARNING: Color input is list."
              " It will now be converted automatically, "
              "data will be unusable if not normalized between 0 and 255.")
        rgba_color = np.array(rgba_color, dtype=np.uint8)
    elif rgba_color.dtype.kind not in ("u", "i"):
        print("WARNING: Color array is not of type integer or unsigned integer."
              " It will now be converted automatically, "
              "data will be unusable if not normalized between 0 and 255.")
        rgba_color = np.array(rgba_color, dtype=np.uint8)
    ply_str = 'ply\nformat ascii 1.0\nelement vertex {0}\nproperty float x\nproperty float y\nproperty float z\n'\
    'property uint8 red\nproperty uint8 green\nproperty uint8 blue\nproperty uint8 alpha\n'\
    'element face {1}\nproperty list uint8 uint vertex_indices\nend_header\n'.format(len(vertices), len(indices))
    for i in range(len(vertices)):
        v = vertices[i]
        curr_rgba = rgba_color[i]
        ply_str += '{0} {1} {2} {3} {4} {5} {6}\n'.format(v[0], v[1], v[2],
                    curr_rgba[0], curr_rgba[1], curr_rgba[2], curr_rgba[3])
    for face in indices:
        ply_str += '3 {0} {1} {2}\n'.format(face[0], face[1], face[2])
    return ply_str


def ply_vertex_generator(vertices):
    ply_str = ""
    for v in vertices:
        ply_str += '{0} {1} {2}\n'.format(v[0], v[1], v[2])
    return ply_str


def ply_index_generator(indices):
    ply_str = ""
    for face in indices:
        ply_str += '3 {0} {1} {2}\n'.format(face[0], face[1], face[2])
    return ply_str


def make_ply_string_wocolor(indices, vertices, normals, nb_cpus=1):
    """
    Creates a ply str that can be included into a .k.zip for rendering
    in KNOSSOS.

    Parameters
    ----------
    indices : iterable of indices (int)
    vertices : iterable of vertices (int)
    normals : iterable of normals (float)

    Returns
    -------
    str
    """
    # create header
    if not indices.ndim == 2:
        indices = np.array(indices, dtype=np.int).reshape((-1, 3))
    if not vertices.ndim == 2:
        vertices = np.array(vertices, dtype=np.float32).reshape((-1, 3))
    ply_str = 'ply\nformat ascii 1.0\nelement vertex {0}\nproperty float x\nproperty float y\nproperty float z\n'\
    'element face {1}\nproperty list uint8 uint vertex_indices\nend_header\n'.format(len(vertices), len(indices))
    print("Generating ply vertices.")
    params = np.array_split(vertices, 100)
    res = start_multiprocess_imap(ply_vertex_generator, params, nb_cpus=nb_cpus)
    for el in res:
        ply_str += el
    print("Generating ply indices.")
    params = np.array_split(indices, 100)
    res = start_multiprocess_imap(ply_index_generator, params, nb_cpus=nb_cpus)
    for el in res:
        ply_str += el
    return ply_str


def write_ssomesh2kzip(k_path, sso, color=(255, 0, 0, 255), ply_fname="0.ply"):
    """
    Writes meshes of SegmentationObject's belonging to SuperSegmentationObject
    as .ply's to k.zip file.

    Parameters
    ----------
    k_path : str
        path to zip
    sso : SuperSegmentationObject
    color : tuple
        rgba between 0 and 255
    ply_fname : str
    """
    ind, vert = merge_someshes(sso.svs)
    color = np.array(color, np.uint8)
    write_mesh2kzip(k_path, ind, vert, color, ply_fname)


def write_mesh2kzip(k_path, ind, vert, norm, color, ply_fname, nb_cpus=1):
    """
    Writes mesh as .ply's to k.zip file.

    Parameters
    ----------
    k_path : str
        path to zip
    ind : np.array
    vert : np.array
    norm : np.array
    color : tuple or np.array
        rgba between 0 and 255
    ply_fname : str
    """
    if len(vert) == 0:
        return
    if color is not None:
        ply_str = make_ply_string(ind, vert.astype(np.float32), norm, color)
    else:
        ply_str = make_ply_string_wocolor(ind, vert.astype(np.float32), norm,
                                          nb_cpus=nb_cpus)
    write_txt2kzip(k_path, ply_str, ply_fname)


def write_meshes2kzip(k_path, inds, verts, norms, colors, ply_fnames, force_overwrite=False):
    """
    Writes meshes as .ply's to k.zip file.

    Parameters
    ----------
    k_path : str
        path to zip
    ind : list of np.array
    vert : list of np.array
    norm : list of np.array
    color : list of tuple or np.array
        rgba between 0 and 255
    ply_fname : list of str
    force_overwrite : bool
    """
    ply_strs = []
    for i in range(len(inds)):
        vert = verts[i]
        ind = inds[i]
        norm = norms[i]
        color = colors[i]
        if len(vert) == 0:
            raise ValueError("Mesh with zero-length vertex array.")
        if color is not None:
            ply_str = make_ply_string(ind, vert.astype(np.float32), norm, color)
        else:
            ply_str = make_ply_string_wocolor(ind, vert.astype(np.float32), norm)
        ply_strs.append(ply_str)
    texts2kzip(k_path, ply_strs, ply_fnames, force_overwrite=force_overwrite)


def get_bb_size(coords):
    bb_min, bb_max = np.min(coords, axis=0), np.max(coords, axis=0)
    return np.linalg.norm(bb_max - bb_min, ord=2)


def color_factory(c_values, mcmap, alpha=1.0):
    colors = []
    for c_val in c_values:
        curr_color = list(mcmap(c_val))
        curr_color[-1] = alpha
        colors.append(curr_color)
    return np.array(colors)


def compartmentalize_mesh(ssv, pred_key_appendix=""):
    """
    Splits SuperSegmentationObject mesh into axon, dendrite and soma. Based
    on axoness prediction of SV's contained in SuperSuperVoxel ssv.

    Parameters
    ----------
    sso : SuperSegmentationObject
    pred_key_appendix : str
        Specific version of axoness prediction

    Returns
    -------
    np.array
        Majority label of each face / triangle in mesh indices;
        triangulation is assumed. If majority class has n=1, majority label is
        set to -1.
    """
    preds = np.array(start_multiprocess_obj("axoness_preds",
                                             [[sv, {"pred_key_appendix": pred_key_appendix}]
                                                for sv in ssv.svs],
                                               nb_cpus=ssv.nb_cpus))
    preds = np.concatenate(preds)
    locs = ssv.sample_locations()
    pred_coords = np.concatenate(locs)
    assert pred_coords.ndim == 2, "Sample locations of ssv have wrong shape."
    assert pred_coords.shape[1] == 3, "Sample locations of ssv have wrong shape."
    ind, vert, axoness = ssv._pred2mesh(pred_coords, preds, k=3, colors=(0, 1, 2))
    # get axoness of each vertex where indices are pointing to
    ind_comp = axoness[ind]
    ind = ind.reshape(-1, 3)
    vert = vert.reshape(-1, 3)
    norm = ssv.mesh[2].reshape(-1, 3)
    ind_comp = ind_comp.reshape(-1, 3)
    ind_comp_maj = np.zeros((len(ind)), dtype=np.uint8)
    for ii in range(len(ind)):
        triangle = ind_comp[ii]
        cnt = Counter(triangle)
        ax, n = cnt.most_common(1)[0]
        if n == 1:
            ax = -1
        ind_comp_maj[ii] = ax
    comp_meshes = {}
    for ii, comp_type in enumerate(["axon", "dendrite", "soma"]):
        comp_ind = ind[ind_comp_maj == ii].flatten()
        unique_comp_ind = np.unique(comp_ind)
        comp_vert = vert[unique_comp_ind].flatten()
        if len(ssv.mesh[2]) != 0:
            comp_norm = norm[unique_comp_ind].flatten()
        else:
            comp_norm = ssv.mesh[2]
        remap_dict = {}
        for i in range(len(unique_comp_ind)):
            remap_dict[unique_comp_ind[i]] = i
        comp_ind = np.array([remap_dict[i] for i in comp_ind], dtype=np.uint)
        comp_meshes[comp_type] = [comp_ind, comp_vert, comp_norm]
    return comp_meshes


def id2rgb(vertex_id):
    """
    Transforms ID value of single sso vertex into the unique RGD colour.

    Parameters
    ----------
    vertex_id : int

    Returns
    -------
    np.array
        RGB values [1, 3]
    """
    red = vertex_id % 256
    green = (vertex_id/256) % 256
    blue = (vertex_id/256/256) % 256
    colour = np.array([red, green, blue], dtype=np.uint8)
    return colour.squeeze()


def id2rgb_array(id_arr):
    """
    Transforms ID values into the array of RGBs labels based on 'idtorgb'.
    Note: Linear retrieval time. For small N preferable.

    Parameters
    ----------
    id_arr : np.array
        ID values [N, 1]

    Returns
    -------
    np.array
        RGB values.squeezed [N, 3]
    """

    if np.max(id_arr) > 256**3:
        raise ValueError("Overflow in vertex ID array.")
    if id_arr.ndim == 1:
        id_arr = id_arr[:, None]
    elif id_arr.ndim == 2:
        assert id_arr.shape[1] == 1, "ValueError: unsupported shape"
    else:
        raise ValueError("Unsupported shape")
    rgb_arr = np.apply_along_axis(id2rgb, 1, id_arr)
    return rgb_arr.squeeze()


@jit
def id2rgb_array_contiguous(id_arr):
    """
    Transforms ID values into the array of RGBs labels based on the assumption
    that 'id_arr' is contiguous index array from 0...len(id_arr).
    Same mapping as 'id2rgb_array'.
    Note: Constant retrieval time. For large N preferable.

    Parameters
    ----------
    id_arr : np.array
        ID values [N, 1]

    Returns
    -------
    np.array
        RGB values.squeezed [N, 3]
    """
    if id_arr.squeeze().ndim > 1:
        raise ValueError("Unsupported index array shape.")
    nb_ids = len(id_arr.squeeze())
    if nb_ids >= 256**3:
        raise ValueError("Overflow in vertex ID array.")
    x1 = np.arange(256).astype(np.uint8)
    x2 = np.arange(256).astype(np.uint8)
    x3 = np.arange(256).astype(np.uint8)
    xx1, xx2, xx3 = np.meshgrid(x1, x2, x3, sparse=False, copy=False)
    rgb_arr = np.concatenate([xx3.flatten()[:, None], xx1.flatten()[:, None],
                              xx2.flatten()[:, None]], axis=-1)[:nb_ids]
    return rgb_arr


def rgb2id(rgb):
    """
    Transforms unique RGB values into soo vertex ID.

    Parameters
    ----------
    rgb: np.array
        RGB values [1, 3]

    Returns
    -------
    np.array
        ID values [1, 1]
    """
    red = rgb[0]
    green = rgb[1]
    blue = rgb[2]
    vertex_id = red + green*256 + blue*(256**2)
    return np.array([vertex_id], dtype=np.uint32)


@jit
def rgb2id_array(rgb_arr):
    """
    Transforms RGB values into IDs based on 'rgb2id'.

    Parameters
    ----------
    rgb_arr : np.array
        RGB values [N, 3]

    Returns
    -------
    np.array
        ID values [N, ]
    """
    if rgb_arr.ndim > 1:
        assert rgb_arr.shape[-1] == 3, "ValueError: unsupported shape"
    else:
        raise ValueError("Unsupported shape")
    rgb_arr_flat = rgb_arr.flatten().reshape((-1, 3))
    mask_arr = (rgb_arr_flat[:, 0] == 255) & (rgb_arr_flat[:, 1] == 255) & \
               (rgb_arr_flat[:, 2] == 255)
    id_arr = np.zeros((len(rgb_arr_flat)), dtype=np.uint32)
    for ii in range(len(rgb_arr_flat)):
        if mask_arr[ii]:
            continue
        rgb = rgb_arr_flat[ii]
        id_arr[ii] = rgb[0] + rgb[1]*256 + rgb[2]*(256**2)
    background_ix = np.max(id_arr) + 1  # convention: The highest index value in index view will correspond to the background
    id_arr[mask_arr] = background_ix
    return id_arr.reshape(rgb_arr.shape[:-1])
