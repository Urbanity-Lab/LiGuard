# contains point-cloud processing algorithms

import os
import sys

import numpy as np

from gui.logger_gui import Logger

def crop(data_dict: dict, cfg_dict: dict):
    """
    Crop the point cloud data based on the specified limits.

    Args:
        data_dict (dict): A dictionary containing the data.
        cfg_dict (dict): A dictionary containing the configuration parameters.

    Returns:
        None
    """
    
    # get logger object from data_dict
    if 'logger' in data_dict: logger:Logger = data_dict['logger']
    else: print('[algo->lidar.py->crop]: No logger object in data_dict. It is abnormal behavior as logger object is created by default. Please check if some script is removing the logger key in data_dict.'); return

    # check if required data is present in data_dict
    if "current_point_cloud_numpy" not in data_dict:
        logger.log('[algo->lidar.py->crop]: current_point_cloud_numpy not found in data_dict', Logger.ERROR)
        return
    
    # get point cloud and crop limits
    pcd = data_dict['current_point_cloud_numpy']
    min_xyz = cfg_dict['proc']['lidar']['crop']['min_xyz']
    max_xyz = cfg_dict['proc']['lidar']['crop']['max_xyz']
    
    # create conditions for cropping
    x_condition = np.logical_and(min_xyz[0] <= pcd[:, 0], pcd[:, 0] <= max_xyz[0])
    y_condition = np.logical_and(min_xyz[1] <= pcd[:, 1], pcd[:, 1] <= max_xyz[1])
    z_condition = np.logical_and(min_xyz[2] <= pcd[:, 2], pcd[:, 2] <= max_xyz[2])
    
    # Update the point cloud in data_dict
    data_dict['current_point_cloud_numpy'] = pcd[x_condition & y_condition & z_condition]
    data_dict['current_point_cloud_point_colors'] = np.ones((data_dict['current_point_cloud_numpy'].shape[0], 3), dtype=np.float32)
    
def project_image_pixel_colors(data_dict: dict, cfg_dict: dict):
    """
    Projects the colors of image pixels onto the point cloud.

    Args:
        data_dict (dict): A dictionary containing the required data for the operation.
        cfg_dict (dict): A dictionary containing configuration parameters.

    Returns:
        None
    """

    # get logger object from data_dict
    if 'logger' in data_dict: logger:Logger = data_dict['logger']
    else: print('[algo->lidar.py->project_image_pixel_colors]: No logger object in data_dict. It is abnormal behavior as logger object is created by default. Please check if some script is removing the logger key in data_dict.'); return
    
    # check if required data is present in data_dict
    if "current_point_cloud_numpy" not in data_dict:
        logger.log('[algo->lidar.py->project_image_pixel_colors]: current_point_cloud_numpy not found in data_dict', Logger.ERROR)
        return
    if "current_image_numpy" not in data_dict:
        logger.log('[algo->lidar.py->project_image_pixel_colors]: current_image_numpy not found in data_dict', Logger.ERROR)
        return
    if "current_calib_data" not in data_dict:
        logger.log('[algo->lidar.py->project_image_pixel_colors]: current_calib_data not found in data_dict', Logger.ERROR)
        return
    
    # Extract required data
    img_np = data_dict['current_image_numpy']
    Tr_velo_to_cam = data_dict['current_calib_data']['Tr_velo_to_cam']
    R0_rect = data_dict['current_calib_data']['R0_rect']
    P2 = data_dict['current_calib_data']['P2']
    
    data_dict['current_point_cloud_point_colors'] = np.ones((data_dict['current_point_cloud_numpy'].shape[0], 3), dtype=np.float32) # N X 3(RGB)
    # Convert lidar coordinates to homogeneous coordinates
    lidar_coords_Nx4 = np.hstack((data_dict['current_point_cloud_numpy'][:,:3], np.ones((data_dict['current_point_cloud_numpy'].shape[0], 1))))
    
    # Project lidar points onto the image plane
    pixel_coords = P2 @ R0_rect @ Tr_velo_to_cam @ lidar_coords_Nx4.T
    
    # Normalize pixel coordinates
    normalized_pixel_coords_2d = pixel_coords[:2] / (pixel_coords[2] + 1e-8)
    normalized_pixel_coords_2d = normalized_pixel_coords_2d.T
    normalized_pixel_coords_2d = normalized_pixel_coords_2d.astype(int)
    
    # Filter out coordinates that are outside the image boundaries
    valid_coords = np.logical_and.reduce((pixel_coords[2,:] > 0, normalized_pixel_coords_2d[:, 0] >= 0, normalized_pixel_coords_2d[:, 0] < img_np.shape[1], normalized_pixel_coords_2d[:, 1] >= 0, normalized_pixel_coords_2d[:, 1] < img_np.shape[0]))
    # Update the point cloud colors in data_dict corresponding to the valid pixel coordinates
    data_dict['current_point_cloud_point_colors'][valid_coords] = img_np[normalized_pixel_coords_2d[valid_coords][:, 1], normalized_pixel_coords_2d[valid_coords][:, 0]] / 255.0
    
def BGFilterSTDF(data_dict: dict, cfg_dict: dict):
    """
    Applies Background Filter using Spatio-Temporal Density Filtering (BGFilterSTDF) to the point cloud data.

    Args:
        data_dict (dict): A dictionary containing the input data and intermediate results.
        cfg_dict (dict): A dictionary containing the configuration parameters.

    Returns:
        None
    """

    # get logger object from data_dict
    if 'logger' in data_dict: logger:Logger = data_dict['logger']
    else: print('[algo->lidar.py->BGFilterSTDF]: No logger object in data_dict. It is abnormal behavior as logger object is created by default. Please check if some script is removing the logger key in data_dict.'); return

    # algo name
    algo_name = 'BGFilterSTDF'

    # dict keys
    query_frames_key = f'{algo_name}_query_frames'
    skip_frames_key = f'{algo_name}_skip_frames'
    params_key = f'{algo_name}_params'
    filter_key = f'{algo_name}_filter'

    # get params
    params = cfg_dict['proc']['lidar']['BGFilterSTDF'].copy()
    live_editable_params = ['background_density_threshold'] # list of params that can be live edited and do not require re-computation of filter
    
    # generate keys for query and skip frames
    all_query_frames_keys = [f'{query_frames_key}_{i}' for i in range(params['number_of_frame_gather_iters'])]
    all_skip_frames_keys = [f'{skip_frames_key}_{i}' for i in range(params['number_of_skip_frames_after_each_iter'])]

    # generate filter if not exists
    if filter_key not in data_dict:
        data_dict[params_key] = params

        # get util functions
        from algo.utils import gather_point_clouds, skip_frames, combine_gathers
        from pcd.utils import get_fixed_sized_point_cloud
        
        # gather frames
        for i in range(params['number_of_frame_gather_iters']):
            gathering_done = gather_point_clouds(data_dict, cfg_dict, all_query_frames_keys[i], params['number_of_frames_in_each_gather_iter'])
            if not gathering_done: return
            skipping_done = skip_frames(data_dict, cfg_dict, all_skip_frames_keys[i], params['number_of_skip_frames_after_each_iter'])
            if not skipping_done: return
            
        # combine gathered frames
        combine_gathers(data_dict, cfg_dict, query_frames_key, all_query_frames_keys)
        assert len(data_dict[query_frames_key]) == params['number_of_frame_gather_iters'] * params['number_of_frames_in_each_gather_iter']
        
        # generate filter
        logger.log(f'[algo->lidar.py->BGFilterSTDF]: Generating filter', Logger.INFO)
        from algo.non_nn.STDF import STDF
        data_dict[query_frames_key] = [get_fixed_sized_point_cloud(frame, params['number_of_points_per_frame']) for frame in data_dict[query_frames_key]]
        data_dict[filter_key] = STDF(data_dict[query_frames_key], params['lidar_range_in_unit_length'], params['bins_per_unit_length'])
        logger.log(f'[algo->lidar.py->BGFilterSTDF]: Filter generated', Logger.INFO)
        data_dict['BGFilterSTDF_set'] = True
    else:
        # recompute filter if non-live-editable params are changed
        condition = False
        for key in params:
            if key in live_editable_params: continue
            condition = condition or data_dict[params_key][key] != params[key]
        # remove all algo keys if params are changed so that filter is re-computed on next call
        if condition:
            keys_to_remove = [key for key in data_dict.keys() if key.startswith(algo_name)]
            for key in keys_to_remove: data_dict.pop(key)
            return
    
    # if filter exists, apply it
    if filter_key in data_dict:
        # get util functions
        from pcd.utils import get_fixed_sized_point_cloud
        # apply filter
        data_dict['current_point_cloud_numpy'] = get_fixed_sized_point_cloud(data_dict['current_point_cloud_numpy'], params['number_of_points_per_frame'])
        data_dict['current_point_cloud_numpy'] = data_dict['current_point_cloud_numpy'][data_dict[filter_key](data_dict['current_point_cloud_numpy'], params['background_density_threshold'])]

def Clusterer_TEPP_DBSCAN(data_dict: dict, cfg_dict: dict):
    """
    Perform TEPP DBSCAN clustering on the current point cloud.

    Theoretically Efficient and Practical Parallel DBSCAN
    https://dl.acm.org/doi/10.1145/3318464.3380582

    Args:
        data_dict (dict): A dictionary containing data for the algorithm.
        cfg_dict (dict): A dictionary containing configuration parameters.

    Returns:
        None
    """
    # get logger object from data_dict
    if 'logger' in data_dict: logger:Logger = data_dict['logger']
    else: print('[algo->lidar.py->Clusterer_TEPP_DBSCAN]: No logger object in data_dict. It is abnormal behavior as logger object is created by default. Please check if some script is removing the logger key in data_dict.'); return
    
    # clear previous key set
    if 'Clusterer_TEPP_DBSCAN_set' in data_dict: data_dict.pop('Clusterer_TEPP_DBSCAN_set')

    # check if required data is present in data_dict
    if "current_point_cloud_numpy" not in data_dict:
        logger.log('[algo->lidar.py->Clusterer_TEPP_DBSCAN]: current_point_cloud_numpy not found in data_dict', Logger.ERROR)
        return
    
    try: DBSCAN = __import__('dbscan', fromlist=['DBSCAN']).DBSCAN
    except:
        logger.log('[algo->lidar.py->Clusterer_TEPP_DBSCAN]: dbscan package not found, please install the `dbscan` package using `pip install dbscan`.', Logger.ERROR)
        return
    
    # get params
    params = cfg_dict['proc']['lidar']['Clusterer_TEPP_DBSCAN']

    # perform clustering
    cluster_label_for_each_point_index, _ = DBSCAN(data_dict['current_point_cloud_numpy'], params['eps'], params['min_samples'])
    point_indices_for_each_cluster_label = [label == cluster_label_for_each_point_index for label in np.unique(cluster_label_for_each_point_index)]

    # create 'current_label_list' if not exists
    if 'current_label_list' not in data_dict:
        data_dict['current_label_list'] = []
        logger.log('[algo->lidar.py->Clusterer_TEPP_DBSCAN]: current_label_list not found in data_dict, creating a new one', Logger.DEBUG)

    # update label list
    for point_indices in point_indices_for_each_cluster_label:
        data_dict['current_label_list'].append({'lidar_cluster': {'point_indices': point_indices}})
    data_dict['Clusterer_TEPP_DBSCAN_set'] = True

def Cluster2Object(data_dict: dict, cfg_dict: dict):
    """
    Converts lidar clusters to object labels and adds them to the current label list.

    Args:
        data_dict (dict): A dictionary containing data for processing.
        cfg_dict (dict): A dictionary containing configuration parameters.

    Returns:
        None
    """

    # get logger object from data_dict
    if 'logger' in data_dict: logger:Logger = data_dict['logger']
    else: print('[algo->lidar.py->Cluster2Object]: No logger object in data_dict. It is abnormal behavior as logger object is created by default. Please check if some script is removing the logger key in data_dict.'); return

    # check if required data is present in data_dict
    if "current_point_cloud_numpy" not in data_dict:
        logger.log('[algo->lidar.py->Cluster2Object]: current_point_cloud_numpy not found in data_dict', Logger.ERROR)
        return
    if 'current_label_list' not in data_dict:
        logger.log('[algo->lidar.py->Cluster2Object]: current_label_list not found in data_dict', Logger.ERROR)
        return
    
    # get params
    params = cfg_dict['proc']['lidar']['Cluster2Object']

    import open3d as o3d
    
    for label_dict in data_dict['current_label_list']:
        if 'lidar_cluster' not in label_dict: continue
        
        # get cluster
        lidar_cluster_dict = label_dict['lidar_cluster']
        point_indices = lidar_cluster_dict['point_indices']
        cluster = data_dict['current_point_cloud_numpy'][point_indices][:, :3]
        
        # create bounding box and get its center, extent, and euler angles
        if params['oriented']:
            try: bbox = o3d.geometry.OrientedBoundingBox.create_from_points(o3d.utility.Vector3dVector(cluster))
            except:
                logger.log('[algo->lidar.py->Cluster2Object]: failed to create an OrientedBoundingBox, skipping ...', Logger.WARNING)
                continue
            lidar_xyz_center = bbox.get_center().astype(np.float32)
            lidar_xyz_extent = bbox.extent.astype(np.float32)
            rotation_matrix = bbox.R.astype(np.float32)
            lidar_xyz_euler_angles = np.array(
                [0.0, # np.arctan2(rotation_matrix[2,1], rotation_matrix[2,2]),
                 0.0, # np.arctan2(-rotation_matrix[2,0], np.sqrt(rotation_matrix[2,1]**2 + rotation_matrix[2,2]**2)),
                 np.arctan2(rotation_matrix[1,0], rotation_matrix[0,0])], dtype=np.float32)
        else:
            try: bbox = o3d.geometry.AxisAlignedBoundingBox.create_from_points(o3d.utility.Vector3dVector(cluster))
            except: continue
            lidar_xyz_center = bbox.get_center().astype(np.float32)
            lidar_xyz_extent = (bbox.get_max_bound() - bbox.get_min_bound()).astype(np.float32)
            lidar_xyz_euler_angles = np.array([0, 0, 0], dtype=np.float32)
        
        # get base length and height of the bounding box
        base_length = lidar_xyz_extent[0] if lidar_xyz_extent[0] > lidar_xyz_extent[1] else lidar_xyz_extent[1]
        height = lidar_xyz_extent[2]

        # check if the cluster belongs to any class
        selected_obj_class = None
        for obj_class, size_constraint in params['size_constraints'].items():
            base_length_range = size_constraint['base_length']
            height_range = size_constraint['height']
            if base_length_range[0] <= base_length < base_length_range[1]: # and height_range[0] <= height < height_range[1]:
                selected_obj_class = obj_class
                break
        
        # if the cluster does not belong to any class, skip it, otherwise add it to the label list
        if selected_obj_class == None:
            logger.log(f'[algo->lidar.py->Cluster2Object]: class could not be determined for cluster with base_length: {base_length} and height: {height}, skipping ...', Logger.WARNING)
            continue
        else:
            if selected_obj_class in params['class_colors']:
                lidar_bbox_color = np.array(params['class_colors'][selected_obj_class], dtype=np.float32)
                camera_bbox_color = (lidar_bbox_color.copy() * 255.0).astype(np.uint8)
            else:
                logger.log(f'[algo->lidar.py->Cluster2Object]: class color not found for class: {selected_obj_class}, using default color', Logger.WARNING)
                lidar_bbox_color = np.array([0, 0, 0], dtype=np.float32)
                camera_bbox_color = (lidar_bbox_color.copy() * 255.0).astype(np.uint8)
            
            label = dict()
            label['class'] = selected_obj_class
            label['lidar_bbox'] = {'lidar_xyz_center': lidar_xyz_center, 'lidar_xyz_extent': lidar_xyz_extent, 'lidar_xyz_euler_angles': lidar_xyz_euler_angles, 'rgb_bbox_color': lidar_bbox_color, 'predicted': True}
            label['camera_bbox'] = {'lidar_xyz_center': lidar_xyz_center, 'lidar_xyz_extent': lidar_xyz_extent, 'lidar_xyz_euler_angles': lidar_xyz_euler_angles, 'rgb_bbox_color': camera_bbox_color, 'predicted': True}
            
            data_dict['current_label_list'].append(label)

def PointPillarDetection(data_dict: dict, cfg_dict: dict):
    """
    Perform object detection using the PointPillar algorithm.

    Original Paper:
    Lang, Alex H., et al. "Pointpillars: Fast encoders for object detection from point clouds."
    Proceedings of the IEEE/CVF conference on computer vision and pattern recognition. 2019.

    The implementation used here is from "https://github.com/zhulf0804/PointPillars".
    
    Args:
        data_dict (dict): A dictionary containing the required data for processing.
        cfg_dict (dict): A dictionary containing the configuration parameters.

    Returns:
        None
    """
    # get logger object from data_dict
    if 'logger' in data_dict: logger:Logger = data_dict['logger']
    else: print('[algo->lidar.py->PointPillarDetection]: No logger object in data_dict. It is abnormal behavior as logger object is created by default. Please check if some script is removing the logger key in data_dict.'); return
    
    # check if required data is present in data_dict
    if "current_point_cloud_numpy" not in data_dict:
        logger.log('[algo->lidar.py->PointPillarDetection]: current_point_cloud_numpy not found in data_dict', Logger.ERROR)
        return
    
    if cfg_dict['proc']['lidar']['PointPillarDetection']['activate_on_key_set'] not in data_dict: return
    

    # algo name and keys used in algo
    algo_name = 'PointPillarDetection'
    model_key = f'{algo_name}_model'
    class_ids_key = f'{algo_name}_class_ids'
    ids_class_key = f'{algo_name}_ids_class'
    pcd_limit_range_key = f'{algo_name}_pcd_limit_range'
    class_color_key = f'{algo_name}_class_color'
    
    # get params
    params = cfg_dict['proc']['lidar'][algo_name]
    
    # imports
    import torch

    # create model if not exists
    if 'PointPillarDetection_model' not in data_dict:
        data_dict[class_ids_key] = {'Pedestrian': 0, 'Cyclist': 1, 'Car': 2}
        data_dict[ids_class_key] = {v:k for k, v in data_dict[class_ids_key].items()}
        min_xyz = cfg_dict['proc']['lidar']['crop']['min_xyz']
        max_xyz = cfg_dict['proc']['lidar']['crop']['max_xyz']
        data_dict[pcd_limit_range_key] = np.array(min_xyz + max_xyz, dtype=np.float32)
        data_dict[class_color_key] = {'Pedestrian': [1, 0, 0], 'Cyclist': [0, 0, 1], 'Car': [0, 1, 0]}

        path = os.path.abspath(os.path.join(data_dict['root_path'], params['path_to_github_repo']))
        if path not in sys.path: sys.path.append(path)
        from algo.nn.PointPillars.model import PointPillars

        data_dict[model_key] = PointPillars(nclasses=len(data_dict[class_ids_key]))
        model_path = os.path.abspath(os.path.join(path, 'pretrained/epoch_160.pth'))
        if torch.cuda.is_available():
            data_dict[model_key].cuda()
            data_dict[model_key].load_state_dict(torch.load(model_path))
        else:
             data_dict[model_key].load_state_dict(torch.load(model_path), map_location=torch.device('cpu'))

        data_dict[model_key].eval()
    
    with torch.no_grad():
        pc_torch = torch.from_numpy(data_dict['current_point_cloud_numpy'])
        if torch.cuda.is_available(): pc_torch = pc_torch.cuda()
        result_filter = data_dict[model_key](batched_pts=[pc_torch], mode='test')[0]

    lidar_bboxes = result_filter['lidar_bboxes']
    labels, scores = result_filter['labels'], result_filter['scores']

    for i in range(len(labels)):
        if scores[i] < params['score_threshold']: continue
        lidar_bbox = lidar_bboxes[i]
        lidar_xyz_center = lidar_bbox[:3]
        lidar_xyz_center[2] += lidar_bbox[5] / 2
        lidar_xyz_extent = lidar_bbox[3:6]
        lidar_xyz_euler_angles = np.array([0, 0, lidar_bbox[6]], dtype=np.float32)
        obj_class = data_dict[ids_class_key][labels[i]]
        lidar_bbox_color = np.array(data_dict[class_color_key][obj_class], dtype=np.float32)
        camera_bbox_color = np.array([i * 255.0 for i in data_dict[class_color_key][obj_class]], dtype=np.uint8)

        label = dict()
        label['class'] = obj_class
        label['lidar_bbox'] = {'lidar_xyz_center': lidar_xyz_center, 'lidar_xyz_extent': lidar_xyz_extent, 'lidar_xyz_euler_angles': lidar_xyz_euler_angles, 'rgb_bbox_color': lidar_bbox_color, 'predicted': True}
        label['camera_bbox'] = {'lidar_xyz_center': lidar_xyz_center, 'lidar_xyz_extent': lidar_xyz_extent, 'lidar_xyz_euler_angles': lidar_xyz_euler_angles, 'rgb_bbox_color': camera_bbox_color, 'predicted': True}

        if 'current_label_list' not in data_dict: data_dict['current_label_list'] = []
        data_dict['current_label_list'].append(label)