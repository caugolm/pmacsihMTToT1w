#!/usr/bin/env python

import antsnetct

from antsnetct import ants_helpers,bids_helpers,system_helpers

import argparse
import glob
import json
import logging
import os
import sys
import tempfile

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

    The T1w image is registered to the ihMT magnitude first echo, using ANTs, with a rigid transform.

    The DKT31 labels are masked by GM in the T1w space, and then resampled into the ihMT space.
    HOA labels are also resampled into the ihMT space, but these are not masked.

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

    # copy the ref image to output dataset
    bids_helpers.image_to_bids(ihmt_n4_masked,
                              output_dataset,
                              ihmt_image_bids.get_rel_path(),
                              metadata={'Sources': [ihmt_image_bids.get_uri(relative=False)]})

    # Mask DKT31 labels by GM in T1w space, then resample to ihMT space
    dkt31_bids = bids_helpers.BIDSImage(antsnetct_dataset,
                                        t1w_bids.get_derivative_rel_path_prefix() + '_seg-dkt31Propagated_dseg.nii.gz')

    hoa_seg_bids = bids_helpers.BIDSImage(antsnetct_dataset, t1w_bids.get_derivative_rel_path_prefix() +
                                          '_seg-hoaMasked_dseg.nii.gz')

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


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    t1w_to_ihmt_pipeline()
