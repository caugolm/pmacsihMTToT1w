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

# Helps with CLI help formatting
class RawDefaultsHelpFormatter(
    argparse.RawTextHelpFormatter, argparse.ArgumentDefaultsHelpFormatter
):
    pass

def t1w_to_ihmt_pipeline():

    parser = argparse.ArgumentParser(formatter_class=RawDefaultsHelpFormatter, add_help = False,
                                     description='''Compute label stats in the ihmt space.

    Input is by participant and session,

        '--participant 01 --session MR1'

    Output is to the same dataset.

    ''')
    required_parser = parser.add_argument_group('Required arguments')
    required_parser.add_argument('--input-dataset', help='Input BIDS dataset dir, containing the source images and masks',
                                 type=str, required=True)
    required_parser.add_argument('--label-def-dir', help='Directory containing label definition files, eg dkt31.tsv',
                                 type=str, required=True)
    required_parser.add_argument('--participant', '--subject', help='Participant to process', type=str, required=True)
    required_parser.add_argument('--session', help='Session to process.', type=str, default=None, required=True)
    optional_parser = parser.add_argument_group('Optional arguments')
    optional_parser.add_argument('-h', '--help', action='help', help='show this help message and exit')
    optional_parser.add_argument('--verbose', help='Verbose output from subcommands', action='store_true')

    if len(sys.argv) == 1:
        parser.print_usage()
        print(f"\nRun {os.path.basename(sys.argv[0])} --help for more information")
        sys.exit(1)

    args = parser.parse_args()

    print('Parsed args: ' + str(args))

    system_helpers.set_verbose(args.verbose)

    input_dataset = args.input_dataset
    participant = args.participant
    session = args.session

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

    print('Input dataset path: ' + input_dataset)
    print('Input dataset name: ' + input_dataset_description['Name'])

    with tempfile.TemporaryDirectory(suffix=f"ihmt_label_stats_{participant}.tmpdir") as work_dir:
        # get segmentations and compute label stats
        dkt31_label_def = os.path.join(args.label_def_dir, 'dkt31.tsv')
        hoa_label_def = os.path.join(args.label_def_dir, 'hoa.tsv')

        mtr = glob.glob(os.path.join(input_dataset, f"sub-{participant}", f"ses-{session}", 'anat',
                                        f"sub-{participant}_ses-{session}_*_part-mag_ihMTR.nii.gz"))[0]

        mtr_relpath = os.path.relpath(mtr, input_dataset)

        mtr_bids = bids_helpers.BIDSImage(input_dataset, mtr_relpath)

        dkt31_bids = mtr_bids.get_derivative_image('_space-ihmt_seg-dkt31_dseg.nii.gz')

        hoa_bids = mtr_bids.get_derivative_image('_space-ihmt_seg-hoa_dseg.nii.gz')

        antsnetct.parcellation_pipeline.make_label_stats(dkt31_bids, dkt31_label_def, work_dir, compute_label_geometry=True,
                                                         scalar_images=[mtr_bids], scalar_descriptions=['ihMTR'])

        antsnetct.parcellation_pipeline.make_label_stats(hoa_bids, hoa_label_def, work_dir, compute_label_geometry=True,
                                                         scalar_images=[mtr_bids], scalar_descriptions=['ihMTR'])


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    t1w_to_ihmt_pipeline()
