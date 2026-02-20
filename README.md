# pmacsihMTToT1w

Scripts for aligning T1w to ihMT and transferring segmentations to ihMT space

## Usage

### Gather inputs

This step copies one T1w and extracts the ihMTR image 
from the ihmt_proc directory.

The choice of T1w is made according to the FTDC heuristic, if multiple T1w images exist in
the session.

Example command:

```bash
pmacsihMTToT1w/bin/gather_t1w_ihmt_inputs.sh \
  -a /project/ftdc_pipeline/data/antsnetct_062 \
  -o $PWD/ihmtDistCorrInput \
  -q /project/ftdc_misc/ihmt/proc \
  lists/test_batch.txt
```

Output structure:

```
ihmtDistCorrInput/
├── sub-001/
    ├── ses-01/
        |--- anat/
             └── sub-001_ses-01_desc-preproc_T1w.nii.gz
                 sub-001_ses-01_desc-antsnetct_mask.nii.gz
                 sub-001_ses-01_desc-ihmtsomething.nii.gz
                 sub-001_ses-01_desc-ihmtsomething_synthStrip_mask.nii.gz
```


### synthstrip brain extraction

This step applies synthstrip to both the T1w and the GRE magnitude image, to generate a
consistent brain mask for optimal alignment. Note that the brain mask used for
registration may be different from the brain mask used in either the T1w or QSM pipelines;
the purpose is merely to provide a consistent brain definition for registration.

Example command:

```bash
pmacsQSMToT1w/bin/synthstrip_t1w_ihmt.sh \
  -c 0 \
  -i ${PWD}/ihmtDistCorrInput \
  lists/test_batch.txt
```

This adds the following files to each session directory:

```
qsmDistCorrInput/
├── sub-001/
    ├── ses-01/
        |--- anat/
             └── sub-001_ses-01_desc-synthstrip_mask.nii.gz
                 sub-001_ses-01_desc-ihMTRSynthstrip_mask.nii.gz
```

if the `-c 1` option is used, a brain mask is also defined with CSF removed from the
cortical exterior. This sometimes improves registration performance by eliminating dura /
skull edges that can have different contrast in T1w vs other images.


### Registration and label transfer

This step performs registration of the T1w to the ihMTR image, and
transfers segmentations from T1w space to ihMT space. It uses the masks generated
in the previous step to focus the registration on brain tissue.

Example command:

```bash
pmacsihMTToT1w/bin/register_t1w_to_ihmt.sh \
  -a /project/ftdc_pipeline/data/antsnetct_062 \
  -i ${PWD}/qsmDistCorrInput \
  -o ${PWD}/t1wToihMT \
  -m synthstrip \
  lists/test_batch.txt
```

The output is to a new BIDS derivative dataset, with the following structure:

```t1wToihMT/
├── sub-001/
    ├── ses-01/
        |--- anat/
                └── sub-001_ses-01_from-T1w_to-ihmt_mode-image_xfm.mat
                    sub-001_ses-01_space-ihmt_T1w.nii.gz
                    sub-001_ses-01_space-ihmt_seg-dkt31_dseg.nii.gz
                    sub-001_ses-01_space-ihmt_seg-hoa_dseg.nii.gz
```