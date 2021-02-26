import numpy as np

from xml.etree import ElementTree
from czifile import CziFile
from multiprocessing import cpu_count
from napari_plugin_engine import napari_hook_implementation
from pathlib import Path


@napari_hook_implementation
def napari_get_reader(path):
    if isinstance(path, list):
        if any(Path(p).suffix.lower() != '.czi' for p in path):
            return None
    else:
        if Path(path).suffix.lower() != '.czi':
            return None
    return reader_function


def reader_function(path):
    paths = [path] if not isinstance(path, list) else path
    layer_data = []
    for path in paths:
        with CziFile(path) as czi_file:
            data = czi_file.asarray(max_workers=cpu_count())
            czi_metadata = ElementTree.fromstring(czi_file.metadata())
            scale_x = _parse_scaling(czi_metadata, 'X', multiplier=10. ** 6)
            scale_y = _parse_scaling(czi_metadata, 'Y', multiplier=10. ** 6)
            scale_z = _parse_scaling(czi_metadata, 'Z', multiplier=10. ** 6)
            scale_t = _parse_scaling(czi_metadata, 'T')
            axis_indices = []
            shared_metadata = {
                'rgb': False,
                'scale': (scale_t, scale_z, scale_y, scale_x),
            }
            if 'S' in czi_file.axes:
                axis_indices.append(czi_file.axes.index('S'))
            else:
                axis_indices.append(0)
                data = np.expand_dims(data, 0)
            if 'T' in czi_file.axes:
                axis_indices.append(czi_file.axes.index('T'))
            else:
                axis_indices.append(data.ndim)
                data = np.expand_dims(data, -1)
            if 'Z' in czi_file.axes:
                axis_indices.append(czi_file.axes.index('Z'))
            else:
                axis_indices.append(data.ndim)
                data = np.expand_dims(data, -1)
            if 'C' in czi_file.axes:
                shared_metadata['channel_axis'] = 2
                channel_names = _parse_channel_names(czi_file, czi_metadata)
                if channel_names is not None:
                    shared_metadata['name'] = channel_names
                axis_indices.append(czi_file.axes.index('C'))
            else:
                axis_indices.append(data.ndim)
                data = np.expand_dims(data, -1)
            axis_indices.append(czi_file.axes.index('Y'))
            axis_indices.append(czi_file.axes.index('X'))
            if '0' in czi_file.axes:
                shared_metadata['rgb'] = True
                axis_indices.append(czi_file.axes.index('0'))
            n = len(axis_indices)
            for axis_index in range(len(czi_file.axes)):
                if axis_index not in axis_indices:
                    axis_indices.append(axis_index)
            data = data.transpose(axis_indices)
            data.shape = data.shape[:n]
            for series_index, series_data in enumerate(data):
                translate_t = _get_translation(czi_file, series_index, 'T') * scale_t
                translate_z = _get_translation(czi_file, series_index, 'Z') * scale_z
                translate_y = _get_translation(czi_file, series_index, 'Y') * scale_y
                translate_x = _get_translation(czi_file, series_index, 'X') * scale_x
                metadata = {
                    **shared_metadata,
                    'translate': (translate_t, translate_z, translate_y, translate_x),
                }
                if 'name' in metadata:
                    metadata['name'] = [f'S{series_index:02d} {channel_name}' for channel_name in metadata['name']]
                layer_data.append((series_data, metadata, 'image'))
    return layer_data


def _parse_scaling(czi_metadata: ElementTree.Element, dimension: str, multiplier: float = 1.) -> float:
    scale_element = czi_metadata.find(f'.//Metadata/Scaling/Items/Distance[@Id="{dimension}"]/Value')
    if scale_element is not None:
        return float(scale_element.text) * multiplier
    return 1.


def _parse_channel_names(czi_file: CziFile, czi_metadata: ElementTree.Element):
    channel_elements = czi_metadata.findall('.//Metadata/Information/Image/Dimensions/Channels/Channel')
    if len(channel_elements) == czi_file.shape[czi_file.axes.index('C')]:
        return [c.attrib.get('Name', c.attrib['Id']) for c in channel_elements]
    return None


def _get_translation(czi_file: CziFile, series_index: int, dimension: str) -> float:
    return min((
        dim_entry.start
        for dir_entry in czi_file.filtered_subblock_directory
        for dim_entry in dir_entry.dimension_entries
        if dim_entry.dimension == dimension and series_index in _get_series_indices(dir_entry)
    ), default=0.)


def _get_series_indices(directory_entry):
    return (dim_entry.start for dim_entry in directory_entry.dimension_entries if dim_entry.dimension == 'S')
