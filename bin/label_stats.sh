#!/bin/bash

module load apptainer/1.4.1

scriptPath=$(readlink -f "$0")
scriptDir=$(dirname "${scriptPath}")
# Repo base dir under which we find bin/ and containers/
repoDir=${scriptDir%/bin}

inputBIDS=""

container="${repoDir}/containers/antsnetct-0.6.2.sif"

function usage() {
  echo "Usage:
  $0 -i ihmt_t1w_dataset subj_sess_list.csv
  "
}

if [[ $# -eq 0 ]]; then
  usage
  exit 1
fi

function help() {
cat << HELP
  `usage`

  Wrapper script to compute label stats on ihMT images using labels from the T1w.

  Required args:

    -i ihmt_t1w_dataset : BIDS dataset dir, containing the ihMT images and labels from the T1w space. Output is to the same
                          dataset.

  Positional args:

    subj_sess_list.csv : CSV file with participants and sessions to process, one per line, no header.


  Output:

    For each of seg-dkt31 and seg-hoa, label stats are computed on the ihMTR image.




HELP

}

antsnetct_dataset=""
input_dataset=""
mask_method=""
output_dataset=""

while getopts "i:h" opt; do
  case $opt in
    i) input_dataset=$OPTARG;;
    h) help; exit 1;;
    \?) echo "Unknown option $OPTARG"; exit 2;;
    :) echo "Option $OPTARG requires an argument"; exit 2;;
  esac
done

shift $((OPTIND - 1))

imageList=$(readlink -f "$1")

date=`date +%Y%m%d`

mkdir -p ${input_dataset}/code/logs

export APPTAINERENV_TMPDIR="/tmp"

nthreads=2

export APPTAINERENV_ITK_GLOBAL_DEFAULT_NUMBER_OF_THREADS=$nthreads
export APPTAINERENV_OMP_NUM_THREADS=$nthreads

for line in $(cat ${imageList}); do
  participant=$(echo ${line} | cut -d ',' -f 1)
  session=$(echo ${line} | cut -d ',' -f 2)

  echo "Submitting label stats for participant ${participant}, session ${session}"

  bsub \
    -cwd . \
    -o "${input_dataset}/code/logs/label_stats_${participant}_${session}_${date}_%J.txt" \
    -n $nthreads \
    -J "labelStats_${participant}_${session}" \
    apptainer exec \
      --containall \
      -B /scratch:/tmp,${input_dataset},${repoDir},${imageList} \
      ${container} \
        ${repoDir}/scripts/label_stats.py \
        --input-dataset ${input_dataset} \
        --label-def-dir ${repoDir}/label_def \
        --participant ${participant} \
        --session ${session} \
        --verbose
  sleep 1

done
