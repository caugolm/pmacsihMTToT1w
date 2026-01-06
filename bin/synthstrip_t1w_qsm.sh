#!/bin/bash

module load apptainer/1.4.1

scriptPath=$(readlink -f "$0")
scriptDir=$(dirname "${scriptPath}")
# Repo base dir under which we find bin/ and containers/
repoDir=${scriptDir%/bin}

container="${repoDir}/containers/freesurfer-8.1.0.sif"

function usage() {
  echo "Usage:
  $0 [-h] [-c 0/1] -i input_ds subj_sess_list.csv
  "
}

if [[ $# -eq 0 ]]; then
  usage
  echo "Run with -h for help"
  exit 1
fi

function help() {
cat << HELP
  `usage`

  This is a wrapper script that does synthstrip brain extraction on T1w and QSM images in a BIDS dataset. These masks are
  used to provide a consistent brain extraction across modalities for registration, and are independent of sepia or the
  antsnetct processing.

  Images are run serially, each takes a couple of minutes. Full parallel processing is not implemented to limit memory
  usage, but it should be safe to submit a few batches in parallel.

  Required args:

    -i input dataset, as produced by gather_t1w_qsm_inputs.sh

  Optional args:

    -c 0/1
        If 1, additional masks without CSF are created. Default is 0.

  Positional args:

    subj_sess_list.csv


  Output:

  Output is in the same dataset as the input. Derivative masks of the T1w and QSM images are created with suffixes

    _desc-synthstrip_mask.nii.gz

  If -c 1 is specified, additional masks without CSF are created with suffixes

    _desc-synthstripNoCSF_mask.nii.gz


HELP

}

imageList=""
inputBIDS=""
doNoCSFMask=0

while getopts "i:c:h" opt; do
  case $opt in
    i) inputBIDS=$OPTARG;;
    c) doNoCSFMask=$OPTARG;;
    h) help; exit 1;;
    \?) echo "Unknown option $OPTARG"; exit 2;;
    :) echo "Option $OPTARG requires an argument"; exit 2;;
  esac
done

shift $((OPTIND - 1))

imageList=$1

if [[ -z "${inputBIDS}" ]]; then
  echo "Error: input dataset must be specified with -i"
  exit 1
fi

if [[ -z "${imageList}" ]]; then
  echo "Error: input subject/session list must be provided as positional argument"
  exit 1
fi

date=`date +%Y%m%d`

mkdir -p ${inputBIDS}/code/logs

bsub \
  -cwd . \
  -n 2 \
  -J synthstrip_t1w_qsm \
  -o "${inputBIDS}/code/logs/synthstrip_t1w_qsm_${date}_%J.txt" \
    ${repoDir}/scripts/synthstrip_t1w_qsm.sh \
      -f ${container} \
      -i ${inputBIDS} \
      -c ${doNoCSFMask} \
      ${imageList}