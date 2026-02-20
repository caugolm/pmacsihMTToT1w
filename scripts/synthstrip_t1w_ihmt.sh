#!/bin/bash

ihmtDistcorrInputDir=""
container=""
subjSessInputFile=""

doNoCSF=0

if [[ $# -eq 0 ]]; then
    echo "Usage: $0 -i ihmtDistcorrInputDir -f fs_container [-c make no csf masks as well (0)/1] input_subj_sess_list.txt"
    exit 1
fi

while getopts "i:f:c:" opt; do
    case $opt in
        i) ihmtDistcorrInputDir=$OPTARG ;;
        f) container=$OPTARG ;;
        c) doNoCSF=$OPTARG;;
        *) echo "Invalid option: -$OPTARG" >&2 ;;
    esac
done

shift $((OPTIND - 1))
subjSessInputFile=$1

if [[ ! -f "$subjSessInputFile" ]]; then
    echo "Subject-session input file '${subjSessInputFile}' not found"
    exit 1
fi
if [[ ! -d "$ihmtDistcorrInputDir" ]]; then
    echo "ihMT distcorr input directory '${ihmtDistcorrInputDir}' not found"
    exit 1
fi
if [[ ! -f "$container" ]]; then
    echo "Container file '${container}' not found"
    exit 1
fi

for line in `cat $subjSessInputFile`; do
    subj=${line%,*}
    sess=${line#*,}

    echo "Processing $subj $sess"

    # There should be one of each of these images selected by the gather script
    t1w=$(ls ${ihmtDistcorrInputDir}/sub-${subj}/ses-${sess}/anat/sub-${subj}_ses-${sess}*_desc-preproc_T1w.nii.gz)
    mag=$(ls ${ihmtDistcorrInputDir}/sub-${subj}/ses-${sess}/anat/sub-${subj}_ses-${sess}*_ihMTR.nii.gz)

    t1w_derivative_root=${t1w%_desc-preproc_T1w.nii.gz}

    t1w_mask=${t1w_derivative_root}_desc-synthstrip_mask.nii.gz
    t1w_mask_nocsf=${t1w_derivative_root}_desc-synthstripNoCSF_mask.nii.gz

    ihmtr_mask=${ihmtDistcorrInputDir}/sub-${subj}/ses-${sess}/anat/sub-${subj}_ses-${sess}_desc-ihMTRSynthstrip_mask.nii.gz
    ihmtr_mask_nocsf=${ihmtDistcorrInputDir}/sub-${subj}/ses-${sess}/anat/sub-${subj}_ses-${sess}_desc-ihMTRSynthstripNoCSF_mask.nii.gz

    if [[ ! -f "${t1w_mask}" ]]; then

        apptainer exec --containall -B $ihmtDistcorrInputDir ${container} \
            mri_synthstrip \
              --image ${t1w} \
              --mask ${t1w_mask} \
              --threads 2

        apptainer exec --containall -B $ihmtDistcorrInputDir ${container} \
            mri_synthstrip \
              --image ${mag} \
              --mask ${ihmtr_mask} \
              --threads 2

        if [[ $doNoCSF -gt 0 ]]; then

            apptainer exec --containall -B $ihmtDistcorrInputDir ${container} \
                mri_synthstrip \
                  --image ${t1w} \
                  --mask ${t1w_mask_nocsf} \
                  --threads 2 \
                  --no-csf

            apptainer exec --containall -B $ihmtDistcorrInputDir ${container} \
                mri_synthstrip \
                  --image ${mag} \
                  --mask ${ihmtr_mask_nocsf} \
                  --threads 2
        fi
    else
        echo "T1w mask already exists for $subj $sess, skipping..."
    fi

done
