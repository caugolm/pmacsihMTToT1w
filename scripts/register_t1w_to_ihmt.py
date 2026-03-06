#!/usr/bin/env python

import antsnetct

from antsnetct import ants_helpers,bids_helpers,system_helpers
from ants import image_read as ants_image_read
from ants import pad_image 

import argparse
import glob
import json
import logging
import os
import sys
import tempfile
import numpy as np

logger = logging.getLogger(__name__)

# Helps with CLI help formatting
class RawDefaultsHelpFormatter(
    argparse.RawTextHelpFormatter, argparse.ArgumentDefaultsHelpFormatter
):
    pass

def t1w_to_ihmt_pipeline():

    parser = argparse.ArgumentParser(formatter_class=RawDefaultsHelpFormatter, add_help = False,
                                     description='''Registration of T1w images to intra-session ihMT.

    Input is by participant and session,

        '--participant 01 --session MR1'

    Output is to a BIDS derivative dataset.

    The T1w image is registered to the ihMTR, using ANTs, with a rigid transform.

    The DKT31 labels are masked by GM in the T1w space, and then resampled into the ihMT space.
    HOA labels are masked by not CSF and resampled into the ihMT space.
    antsnetct segmentation is resampled into the ihMT space.

    QC processes also run:
        ihMTR heatmap pngs
        ihMT segmentation qc 

    Input requirements:
        - BIDS dataset with T1w images and ANTsNetCT segmentations
        - Directory containing the T1w, ihMT image, and masks

    To get suitable inputs, see `gather_t1w_ihmt_inputs.py`.

    ''')
    required_parser = parser.add_argument_group('Required arguments')
    required_parser.add_argument('--input-dataset', help='Input BIDS dataset dir, containing the source images and masks',
                                 type=str, required=True)
    required_parser.add_argument('--antsnetct-dataset', help='BIDS dataset dir containing the ANTsNetCT derivatives',
                                 type=str, required=True)
    required_parser.add_argument('--participant', '--subject', help='Participant to process', type=str, required=True)
    required_parser.add_argument('--session', help='Session to process.', type=str, default=None, required=True)
    required_parser.add_argument('--output-dataset', help='Output BIDS dataset dir', type=str, required=True)

    optional_parser = parser.add_argument_group('General optional arguments')
    optional_parser.add_argument('--registration-mask-strategy', help='Choice of registration mask, '
                                 'one of "synthstrip" (default), "synthstrip_no_csf", or "no_synthstrip". If no_synthstrip '
                                 'is selected, the original antsnetct brain mask is used for T1w and the nothing brain mask is '
                                 'used for the ihMTR image.', type=str, default='synthstrip')
    optional_parser.add_argument('-h', '--help', action='help', help='show this help message and exit')
    optional_parser.add_argument('--verbose', help='Verbose output from subcommands', action='store_true')

    if len(sys.argv) == 1:
        parser.print_usage()
        print(f"\nRun {os.path.basename(sys.argv[0])} --help for more information")
        sys.exit(1)

    args = parser.parse_args()

    logger.info('Parsed args: ' + str(args))

    system_helpers.set_verbose(args.verbose)

    antsnetct_dataset = args.antsnetct_dataset
    input_dataset = args.input_dataset
    output_dataset = args.output_dataset
    participant = args.participant
    session = args.session

    if (os.path.realpath(input_dataset) == os.path.realpath(output_dataset)):
        raise ValueError('Input and output datasets cannot be the same')

    if os.path.exists(os.path.join(output_dataset, f"sub-{participant}", f"ses-{session}", "anat")):
        logger.info(f"Outputs already exist for participant {participant}, session {session}")
        return

    input_dataset_description = None

    if os.path.exists(os.path.join(input_dataset, 'dataset_description.json')):
        with open(os.path.join(input_dataset, 'dataset_description.json'), 'r') as f:
            input_dataset_description = json.load(f)
    else:
        raise ValueError('Input dataset does not contain a dataset_description.json file')


    if participant is None:
        raise ValueError('Participant must be defined')
    if session is None:
        raise ValueError('Session must be defined')

    logger.info('Input dataset path: ' + input_dataset)
    logger.info('Input dataset name: ' + input_dataset_description['Name'])

    output_dataset_link_paths = [os.path.abspath(input_dataset)]

    bids_helpers.update_output_dataset(output_dataset, input_dataset_description['Name'] + '_t1w_to_ihmt',
                                       output_dataset_link_paths)

    with open(os.path.join(output_dataset, 'dataset_description.json'), 'r') as f:
        output_dataset_description = json.load(f)

    logger.info('Output dataset path: ' + output_dataset)
    logger.info('Output dataset name: ' + output_dataset_description['Name'])

    work_dir_tempfile = tempfile.TemporaryDirectory(suffix=f"antsnetct_bids_{participant}.tmpdir")
    work_dir = work_dir_tempfile.name

    # Get input t1w - this is from the "input t1w" dataset, from gather_t1w_ihmt_inputs.py, and thus only one should exist
    # This is a copy of one of the T1w images from antsnetct - but other T1w might exist in the same session.
    bids_t1w_filter = bids_helpers.get_modality_filter_query('t1w')
    bids_t1w_filter['desc'] = 'preproc'
    bids_t1w_filter['session'] = session

    # There should be only one T1w image in the input dataset
    t1w_bids = bids_helpers.find_participant_images(input_dataset, participant, work_dir, validate=False, **bids_t1w_filter)

    if (len(t1w_bids) != 1):
        raise ValueError(f'Expected one T1w image in input dataset for participant {participant}, session {session}, '
                         f'found {len(t1w_bids)}')

    t1w_bids = t1w_bids[0]

    ihmt_image_bids = bids_helpers.BIDSImage(input_dataset,
                                            os.path.join(f"sub-{participant}", f"ses-{session}", "anat",
                                                         f"sub-{participant}_ses-{session}_acq-ihMTgre2500um_part-mag_ihMTR.nii.gz"))

    # Register T1w to ihMT
    t1w_to_ihmt_reg_output_prefix = os.path.join(work_dir, f"sub-{participant}_ses-{session}_t1w_to_ihmt_")

    ihmt_mask = None
    t1w_mask = None

    if (args.registration_mask_strategy == 'synthstrip'):
        ihmt_mask = bids_helpers.BIDSImage(
            input_dataset,
            os.path.join(f"sub-{participant}", f"ses-{session}", "anat",
                         f"sub-{participant}_ses-{session}_desc-ihMTRSynthstrip_mask.nii.gz")
            )
        t1w_mask = t1w_bids.get_derivative_image('_desc-synthstrip_mask.nii.gz')

    elif (args.registration_mask_strategy == 'synthstrip_no_csf'):
        ihmt_mask = bids_helpers.BIDSImage(
            input_dataset,
            os.path.join(f"sub-{participant}", f"ses-{session}", "anat",
                         f"sub-{participant}_ses-{session}_desc-ihMTRSynthstripNoCSF_mask.nii.gz")
            )
        t1w_mask = t1w_bids.get_derivative_image('_desc-synthstripNoCSF_mask.nii.gz')

    elif (args.registration_mask_strategy == 'no_synthstrip'):
        ihmt_mask = bids_helpers.BIDSImage(
            input_dataset,
            os.path.join(f"sub-{participant}", f"ses-{session}", "anat",
                         f"sub-{participant}_ses-{session}_desc-sepia_mask.nii.gz")
            )
        t1w_mask = bids_helpers.BIDSImage(input_dataset,
                                          t1w_bids.get_derivative_rel_path_prefix() + "_desc-antsnetct_mask.nii.gz")
    else:
        raise ValueError(f"Invalid registration mask strategy: {args.registration_mask_strategy}. "
                         f"Options are 'synthstrip', 'synthstrip_no_csf', or 'no_synthstrip'.")

    if t1w_mask is None or not os.path.exists(t1w_mask.get_path()):
        raise ValueError(f"T1w mask not found for participant {participant}, session {session}")

    # N4 bias correct - do this on the fly for consistency with the brain masks
    t1w_n4 = ants_helpers.n4_bias_correction(t1w_bids.get_path(), t1w_mask.get_path(), work_dir)
    ihmt_n4 = ants_helpers.n4_bias_correction(ihmt_image_bids.get_path(), ihmt_mask.get_path(), work_dir)

    # apply masks
    t1w_n4_masked = ants_helpers.apply_mask(t1w_n4, t1w_mask.get_path(), work_dir)
    ihmt_n4_masked = ants_helpers.apply_mask(ihmt_n4, ihmt_mask.get_path(), work_dir)

    system_helpers.run_command(
        ['antsRegistration',
        '--dimensionality', '3',
        '--float', '0',
        '--output', f'[{t1w_to_ihmt_reg_output_prefix},{t1w_to_ihmt_reg_output_prefix}Warped.nii.gz]',
        '--interpolation', 'Linear',
        '--winsorize-image-intensities', '[0.0,0.999]',
        '--masks', f"[{ihmt_mask.get_path()},{t1w_mask.get_path()}]",
        '--transform', 'Rigid[0.1]',
        '--metric', f'MI[{ihmt_n4_masked},{t1w_n4_masked},1,32,Regular]',
        '--convergence', '[500x250x50,1e-6,10]',
        '--shrink-factors', '4x2x1',
        '--smoothing-sigmas','2x1x0vox'])

    t1w_warped_bids = bids_helpers.image_to_bids(f"{t1w_to_ihmt_reg_output_prefix}Warped.nii.gz", output_dataset,
                                                 t1w_bids.get_derivative_rel_path_prefix() + '_space-ihmt_T1w.nii.gz',
                                                 metadata={'Sources': [t1w_bids.get_uri(relative=False)],
                                                          'SkullStripped': False})

    t1w_to_ihmt_transform = os.path.join(output_dataset,
                                        t1w_bids.get_derivative_rel_path_prefix() + '_from-T1w_to-ihmt_mode-image_xfm.mat')

    system_helpers.copy_file(f"{t1w_to_ihmt_reg_output_prefix}0GenericAffine.mat", t1w_to_ihmt_transform)

    # Register T1w to ihMT
    t1w_to_ihmt_reg_output_prefix = os.path.join(work_dir, f"sub-{participant}_ses-{session}_t1w_to_ihmt_")

    # copy the n4-ed registration ref image to output dataset
    bids_helpers.image_to_bids(ihmt_n4_masked,
                              output_dataset,
                              os.path.join(output_dataset, f"sub-{participant}", f"ses-{session}", "anat", 
                                           f"sub-{participant}_ses-{session}_acq-ihMTgre2500um_part-mag_desc-N4_ihMTR.nii.gz"),
                              metadata={'Sources': [ihmt_image_bids.get_uri(relative=False)]})

    ihmt_masked = ants_helpers.apply_mask(ihmt_image_bids.get_path(), ihmt_mask.get_path(), work_dir)

    # copy the masked ihMT image to output dataset
    ihmt_masked_bids = bids_helpers.image_to_bids(ihmt_masked,
                              output_dataset,
                              ihmt_image_bids.get_rel_path(),
                              metadata={'Sources': [ihmt_image_bids.get_uri(relative=False)]})
    
    # Mask DKT31 labels by GM in T1w space, then resample to ihMT space
    dkt31_bids = bids_helpers.BIDSImage(antsnetct_dataset,
                                        t1w_bids.get_derivative_rel_path_prefix() + '_seg-dkt31Propagated_dseg.nii.gz')

    hoa_seg_bids = bids_helpers.BIDSImage(antsnetct_dataset, t1w_bids.get_derivative_rel_path_prefix() +
                                          '_seg-hoaMasked_dseg.nii.gz')

    seg_bids = bids_helpers.BIDSImage(antsnetct_dataset,
                                        t1w_bids.get_derivative_rel_path_prefix() + '_seg-antsnetct_dseg.nii.gz')

    dkt31_in_ihmt_space = ants_helpers.apply_transforms(ihmt_image_bids.get_path(), dkt31_bids.get_path(),
                                                           [f"{t1w_to_ihmt_reg_output_prefix}0GenericAffine.mat"],
                                                           work_dir,
                                                           interpolation='GenericLabel',
                                                           single_precision=True)

    dkt31_in_ihmt_bids = bids_helpers.image_to_bids(dkt31_in_ihmt_space, output_dataset,
                                                   ihmt_image_bids.get_derivative_rel_path_prefix() + \
                                                    '_space-ihmt_seg-dkt31_dseg.nii.gz',
                                                   metadata={'Sources': [dkt31_bids.get_uri(relative=False)]})

    hoa_in_ihmt_space = ants_helpers.apply_transforms(ihmt_image_bids.get_path(), hoa_seg_bids.get_path(),
                                                         [f"{t1w_to_ihmt_reg_output_prefix}0GenericAffine.mat"],
                                                         work_dir,
                                                         interpolation='GenericLabel',
                                                         single_precision=True)

    hoa_in_ihmt_bids = bids_helpers.image_to_bids(hoa_in_ihmt_space, output_dataset,
                                                 ihmt_image_bids.get_derivative_rel_path_prefix() +
                                                 '_space-ihmt_seg-hoa_dseg.nii.gz',
                                                 metadata={'Sources': [hoa_seg_bids.get_uri(relative=False)]})
    
    seg_in_ihmt_space = ants_helpers.apply_transforms(ihmt_image_bids.get_path(), seg_bids.get_path(),
                                                           [f"{t1w_to_ihmt_reg_output_prefix}0GenericAffine.mat"],
                                                           work_dir,
                                                           interpolation='GenericLabel',
                                                           single_precision=True)

    seg_in_ihmt_bids = bids_helpers.image_to_bids(seg_in_ihmt_space, output_dataset,
                                                   ihmt_image_bids.get_derivative_rel_path_prefix() + \
                                                    '_space-ihmt_seg-antsnetct_dseg.nii.gz',
                                                   metadata={'Sources': [seg_bids.get_uri(relative=False)]})
    compute_qc_stats(ihmt_masked_bids, ihmt_mask, seg_in_ihmt_bids, work_dir, t1w_warped_bids)
    make_ihMTR_qc_plots(ihmt_masked_bids, ihmt_mask.get_path(), work_dir)


def make_ihMTR_qc_plots(ihmt_bids, mask_image, work_dir):
    """Generate tiled QC plots for a ihMTR image heatmap

    Output is written as a derivative of the ihMTR_bids image.

    Parameters:
    -----------
    ihMTR_bids : BIDSImage
        ihMTR image object, should be the masked preprocessed ihMTR image in the output dataset.
    mask_image : image
        Brain mask for the preprocessed ihMTR image.
    work_dir : str
        Path to the working directory.
    """
    # winsorize a bit to boost brightness of the brain
    scalar_image = ants_helpers.winsorize_intensity(ihmt_bids.get_path(), mask_image, work_dir, lower_percentile=0.0,
                                                    upper_iqr_scale=1.5)

    ihmt_rgb = ants_helpers.convert_scalar_image_to_rgb(scalar_image, work_dir, mask=mask_image, colormap='jet', min_value=0.01,
                                                         max_value=.25)

    output_desc_ax = f"qcihMTRAx"
    output_desc_cor = f"qcihMTRCor"

    tiled_ihmtr_ax = ccreate_tiled_mosaic(scalar_image, mask_image, work_dir, overlay=ihmt_rgb,
                                                      overlay_alpha=1, axis=1, pad='mask+5', flip_spec=(0,1), slice_spec=(3,'mask','mask'))
    tiled_ihmtr_cor = ccreate_tiled_mosaic(scalar_image, mask_image, work_dir, overlay=ihmt_rgb,
                                                       overlay_alpha=1, axis=0, pad='mask+5', slice_spec=(3,'mask','mask'))

    system_helpers.copy_file(tiled_ihmtr_ax, ihmt_bids.get_derivative_path_prefix() + f"_desc-{output_desc_ax}.png")
    system_helpers.copy_file(tiled_ihmtr_cor, ihmt_bids.get_derivative_path_prefix() + f"_desc-{output_desc_cor}.png")

# ihmt_masked_bids = ihmt_bids
# ihmt_mask = mask_bids
# seg_in_ihmt_bids = seg_in_ihmt_bids
# none = thick_bids
def compute_qc_stats(ihmt_bids, mask_bids, seg_bids, work_dir, t1w_brain_ihmt_space_bids=None, thick_bids=None, template=None, 
                     template_brain_mask=None):
    """Compute QC statistics for an ihMTR image with segmentation data

    Makes TSV file with some QC statistics for the ihMTR image-space segmentation.

    Parameters:
    -----------
    ihmt_bids : BIDSImage
        ihMTR image object, should be the preprocessed ihMTR image in the output dataset.
    mask_bids : BIDSImage
        Brain mask for the preprocessed ihMTR image.
    seg_bids : BIDSImage
        antsnetct Segmentation image in the ihMTR space.
    work_dir : str
        Path to the working directory.
    t1w_brain_ihmt_space_bids : BIDSImage, optional
        masked T1w brain image in the ihMT space.
    thick_bids : BIDSImage, optional
        ihMTR image in the output dataset.
    template : TemplateImage, optional
        ignored for now Path to the template image. If provided, this is used to compute the correlation between the T1w brain and the
        template.
    template_brain_mask: TemplateImage, optional
        ignored for now Brain mask for the template. Required if template is provided.
    """
    # Read in the images to compute stats
    ihmt_image = ants_image_read(ihmt_bids.get_path())
    mask_image = ants_image_read(mask_bids.get_path())
    seg_image = ants_image_read(seg_bids.get_path())

    mask_vol = mask_image[mask_image > 0].shape[0] * np.prod(mask_image.spacing) / 1000.0 # volume in ml
    seg_vols = [seg_image[seg_image == i].shape[0] * np.prod(seg_image.spacing) / 1000.0 for i in (2, 3, 8, 9, 10, 11)]

    cgm_mask = seg_image == 8
    
    cgm_mean_intensity = ihmt_image[cgm_mask].mean()
    wm_mean_intensity = ihmt_image[seg_image == 2].mean()
    wm_gm_contrast = wm_mean_intensity / cgm_mean_intensity
    csf_mean_intensity = ihmt_image[seg_image == 3].mean()
    bs_mean_intensity = ihmt_image[seg_image == 10].mean()
    sgm_mean_intensity = ihmt_image[seg_image == 9].mean()
    cbm_mean_intensity = ihmt_image[seg_image == 11].mean()


    if thick_bids is not None:
        thick_image = ants_image_read(thick_bids.get_path())
        gm_thickness = thick_image[thick_image > 0.001]
        thick_mean = gm_thickness.mean()
        thick_std = gm_thickness.std()

    if t1w_brain_ihmt_space_bids is not None:
        # template_brain_image = ants_helpers.apply_mask(template.get_path(), template_brain_mask.get_path(), work_dir)
        t1w_template_corr = ants_helpers.image_correlation(t1w_brain_ihmt_space_bids.get_path(), ihmt_bids.get_path(),
                                                           work_dir)

    csf_vol = seg_vols[1]

    non_csf_fraction = 1.0 - csf_vol / mask_vol

    # Write the stats to a TSV file
    with open(ihmt_bids.get_derivative_path_prefix() + '_desc-qc_brainstats.tsv', 'w') as f:
        f.write("metric\tvalue\n")
        f.write(f"cgm_mean_intensity\t{cgm_mean_intensity:.4f}\n")
        f.write(f"wm_mean_intensity\t{wm_mean_intensity:.4f}\n")
        f.write(f"wm_cgm_contrast\t{wm_gm_contrast:.4f}\n")
        f.write(f"csf_mean_intensity\t{csf_mean_intensity:.4f}\n")
        f.write(f"sgm_mean_intensity\t{sgm_mean_intensity:.4f}\n")
        f.write(f"bs_mean_intensity\t{bs_mean_intensity:.4f}\n")
        f.write(f"cbm_mean_intensity\t{cbm_mean_intensity:.4f}\n")
        f.write(f"brain_volume_ml\t{mask_vol:.4f}\n")
        f.write(f"parenchymal_fraction\t{non_csf_fraction:.4f}\n")
        f.write(f"csf_volume_ml\t{csf_vol:.4f}\n")
        f.write(f"gm_volume_ml\t{seg_vols[2]:.4f}\n")
        f.write(f"wm_volume_ml\t{seg_vols[0]:.4f}\n")
        f.write(f"sgm_volume_ml\t{seg_vols[3]:.4f}\n")
        f.write(f"bs_volume_ml\t{seg_vols[4]:.4f}\n")
        f.write(f"cbm_volume_ml\t{seg_vols[5]:.4f}\n")

        if thick_bids is not None:
            f.write(f"thickness_mean\t{thick_mean:.4f}\n")
            f.write(f"thickness_std\t{thick_std:.4f}\n")

        if t1w_brain_ihmt_space_bids is not None:
            f.write(f"t1w_ihmt_corr\t{t1w_template_corr:.4f}\n")


def ccreate_tiled_mosaic(scalar_image, mask, work_dir, overlay=None, tile_shape=(-1, -1), overlay_alpha=0.25, axis=2,
                        pad='mask+4', slice_spec=(3,'mask+8','mask-8'), flip_spec=(1,1), title_bar_text=None,
                        title_bar_font_size=60):
    """Create a tiled mosaic of a scalar image using a colormap.

    Parameters:
    -----------
    scalar_image : str
        Path to scalar image.
    mask : str
        Path to mask image. Required to properly set the bounds of the mosaic images.
    work_dir : str
        Path to working directory.
    overlay : str, optional
        Path to an overlay RGB image.
    tile_shape : list, optional
        Shape of the mosaic. Default is (-1,-1), which attempts to tile in a square shape.
    overlay_alpha : float, optional
        Alpha value for the overlay. Default is 0.25.
    axis : int, optional
        Axis to slice along, one of (0,1,2) for (x,y,z) respectively. Default is 2 = z.
    pad : str, optional
        Padding for the mosaic tiles. Either 'mask[+-]N' or 'N', where N is an integer. Default is 'mask+4', which puts 4
        pixels of space around the bounding box of the mask.
    slice_spec : list, optional
        Slice specification in the form (interval, min, max). By default, the interval is 3, and the min and max are set to
        'mask+8' and 'mask-8' respectively. This starts at an offset of +8 from the first slice within the mask, and ends
        at an offset of -8 from the last slice within the mask. Set to (interval,mask,mask), to set the boundaries to the full
        extent of the mask.
    flip_spec : list, optional
        Flip specification in the form (x,y). Default (1,1) works for LPI input.
    title_bar_text : str, optional
        Text to overlay on the title bar, if required. If not None, a black rectangle is added to the top of the image with
        the specified text centered within it.
    title_bar_font_size : int, optional
        Font size for the title bar text, in points. Default is 60.

    Returns:
    --------
    mosaic_image : str
        Path to mosaic image
    """
    tmp_file_prefix = system_helpers.get_temp_file(work_dir, prefix='mosaic')

    mosaic_file = f"{tmp_file_prefix}_mosaic.png"

    # If pad contains 'mask', we need to extract the amount and pad the inputs accordingly
    # This avoids an ANTs bug but has the pleasant side effect of ensuring that the user
    # can always have as much padding as they request, even if the mask is close to the image boundary
    scalar_input = scalar_image
    mask_input = mask
    overlay_input = overlay

    if isinstance(pad, str) and 'mask' in pad and 0 is 1:
        # pad_image splits the pad_amount between both sides in each dimension
        # CreateTiledMosaic pads by the specified amount on each side, so we double it here
        pad_amount = 2 * (int(pad.split('+')[-1]) + 1)
        pad_spec = [pad_amount, pad_amount, pad_amount]

        padded_scalar = pad_image(scalar_image, pad_spec, work_dir)
        padded_mask = pad_image(mask, pad_spec, work_dir)
        padded_overlay = None
        if overlay is not None:
            padded_overlay = pad_image(overlay, pad_spec, work_dir, image_is_rgb=True)

        scalar_input = padded_scalar
        mask_input = padded_mask
        overlay_input = padded_overlay

    cmd = ['CreateTiledMosaic', '-g', str(1), '-i', scalar_input,  '-x', mask_input, '-o', mosaic_file, '-t',
           f"{tile_shape[0]}x{tile_shape[1]}", '-a', str(overlay_alpha), '-s',
           f"[{slice_spec[0]},{slice_spec[1]},{slice_spec[2]}]", '-d', str(axis), "-f", f"{flip_spec[0]}x{flip_spec[1]}"]


    #cmd = ['CreateTiledMosaic', '-g', 1, '-i', scalar_input,  '-x', mask_input, '-o', mosaic_file, '-t',
    #       f"{tile_shape[0]}x{tile_shape[1]}", '-p', pad, '-a', str(overlay_alpha), '-s',
    #       f"[{slice_spec[0]},{slice_spec[1]},{slice_spec[2]}]", '-d', str(axis), "-f", f"{flip_spec[0]}x{flip_spec[1]}"]

    if overlay is not None:
        cmd.extend(['-r', overlay_input])

    system_helpers.run_command(cmd)

    #if title_bar_text is not None:
    #    mosaic_file = _add_text_to_slice(mosaic_file, title_bar_text, font_size=title_bar_font_size)

    return mosaic_file




if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    t1w_to_ihmt_pipeline()
