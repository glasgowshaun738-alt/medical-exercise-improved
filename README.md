# Medical Software Exercise

This is the exercise refered to in https://gist.github.com/shallowtwist-ben/cb638aae7fdcd78fc36312ac8829a77d.  I've reproduced the background text below for convenience.

## Background

This code is a simplification of the coregistration and spatial transformation code DeepSpin use.

DeepSpin's product is used to perform MRI guided biospy. The patient will come with a High Field MRI (HFI) which was used to diagnose that a biopsy is needed. During the proceedure we capture a Low Field MRI (LFI).

We use the LFI to 'coregister' the HFI. That means we use an algorithm to work out how to manipulate the older HFI image to match the position and current anatomy of the user based on the LFI we just took.

We use the parameters from coregistration to then spatially transform the HFI into a Spatially Transformed High Field Image (STHFI) which has the same image quality as the HFI but is updated to the current positioning of the patient.

## Structure

* [coregistration_exercise.py](./coregistration_exercise.py) - used to simulate spatial transformation of one image to another
* [generate_data.py](./generate_data.py) - **Out of scope**: used to generate the synthetic data
* [helper_functions.py](./helper_functions.py) - **Out of scope**: used to simulate coregistration of one image to another 

The `coregistration_exercise.py` take synthetic data from `./patient_X.XXX.png` and output coregistered images to `output/`.

`get_prostate_location_from_user` is a function which simulates a user clicking on a UI to identify where they want to biopsy.  This is represented as a red circle in the spatially transformed output images.

## Usage

You can clone this code with `git clone https://gist.github.com/c5bdca75d27dd5d53f0b5e0d8380ca88.git`

If you have `uv` installed, you should be able to run `uv sync` to install all the dependencies.

The only required dependency is `pillow`; `ipykernel` is an optional dependency if you want to run an interactive terminal in VS Code.

This code has been tested with `python 3.12.5` / `python 3.10.14` and `uv 0.4.2`.