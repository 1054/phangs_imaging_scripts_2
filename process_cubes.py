# This script post-processes the imaging into science-ready cubes.

import os
import phangsPipeline as pp
import phangsCubePipeline as pcp
import analysisUtils as au
import glob

# -=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=
# Directories and definitions
# -=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=

interferometric_array_list = ['12m', '7m', '12m+7m']
full_array_list = ['12m+7m+tp', '12m+7m', '12m', '7m', '7m+tp']
full_product_list = ['co21','c18o21','13co21']
gal_part_list = pp.list_gal_names()

inroot_dir = '../'
vstring = 'v3_casa'
outroot_dir = '../release/'+vstring+'/'

# -=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=
# Control Flow
# -=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=

# ... a text list. The script will process only these galaxies.

only = []

# ... skip these galaxies
skip = []

# ... start with this galaxy

first = ""
last = ""

# ... set as '12m', '7m', '7m+tp', '12m+7m', or '12m+7m+tp' to process
# only data from that array. Leave it as None to process all data.

just_array = []
#just_array = ['7m']

# ... set as the products to be handled. Valid choices for the basic
# PHANGS data are 'co21', 'c18o21', 'cont', 'co21_chan0', and
# 'c18o21_chan0'. Note that right now cont and chan0 are not tested.

just_product = ['co21']

# ... set these variables to indicate what steps of the script should
# be performed.

rebuild_directories = False

stage_cubes = False
stage_singledish = False

primary_beam_correct = False
convolve_to_round_beam = False

prep_for_feather = False
feather_data = False

prep_for_mosaic = False
mosaic_data = False

cleanup_cubes = False

# -=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=
# Wipe and rebuild if requested
# -=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=

if rebuild_directories:
    pcp.rebuild_directories(outroot_dir=outroot_dir)

# -=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=
# Loop over all galaxies to stage, process, mosaic, and cleanup
# -=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=

for this_loop in ['stage', 'process', 'feather', 'mosaic', 'cleanup']:
    
    print("")
    print("Looping over all galaxies and products.")
    print("... this loop is to: "+this_loop)
    print("")

    before_first = True
    after_last = False

    for gal in gal_part_list:
        
        if len(only) > 0:
            if only.count(gal) == 0:
                print("Skipping "+gal)
                continue

        if len(skip) > 0:
            if skip.count(gal) > 0:
                print("Skipping "+gal)
                continue

        if first != "":
            if gal == first:
                before_first = False
                if before_first:
                    continue
                
        if last != "":
            if after_last == True:
                continue
            if gal == last:
                after_last = True

        for product in full_product_list:
            
            if len(just_product) > 0:
                if just_product.count(product) == 0:
                    print("Skipping "+product)
                    continue
                        
            print(gal, product)

            if this_loop == 'stage' and stage_singledish:
                pcp.phangs_stage_singledish(
                    gal=gal, product=product, 
                    root_dir = outroot_dir, 
                    overwrite=True
                    )
 
            for array in full_array_list:

                if len(just_array) > 0:
                    if just_array.count(array) == 0:
                        print("Skipping "+array)
                        continue

                print("..."+array)

                if this_loop == 'stage' and stage_cubes:
                    if array == "12m+7m+tp" or array == "7m+tp":
                        continue
                    pcp.phangs_stage_cubes(
                        gal=gal, array=array, product=product, 
                        root_dir = outroot_dir, 
                        overwrite=True
                        )                        
                    
                if this_loop == 'process' and primary_beam_correct:
                    if array == "12m+7m+tp" or array == "7m+tp":
                        continue
                    pcp.phangs_primary_beam_correct(
                        gal=gal, array=array, product=product, 
                        root_dir=outroot_dir,
                        overwrite=True
                        )

                if this_loop == 'process' and convolve_to_round_beam:
                    if array == "12m+7m+tp" or array == "7m+tp":
                        continue
                    pcp.phangs_convolve_to_round_beam(
                        gal=gal, array=array, product=product, 
                        root_dir=outroot_dir,
                        overwrite=True
                        )
                    
                if this_loop == 'feather' and prep_for_feather:
                    if array == "12m+7m+tp" or array == "7m+tp":
                        continue
                    pcp.prep_for_feather(
                        gal=gal, array=array, product=product,
                        root_dir=outroot_dir,
                        overwrite=True
                        )

                if this_loop == 'feather' and feather_data:
                    if array == "12m+7m+tp" or array == "7m+tp":
                        continue
                    pcp.phangs_feather_data(
                        gal=gal, array=array, product=product,
                        root_dir=outroot_dir,
                        overwrite=True
                        )

                if this_loop == 'mosaic' and prep_for_mosaic:
                    pcp.prep_for_mosaic(
                        gal=gal, array=array, product=product,
                        root_dir=outroot_dir,
                        overwrite=True
                        )

                if this_loop == 'mosaic' and mosaic_data:
                    pcp.phangs_mosaic_data(
                        gal=gal, array=array, product=product,
                        root_dir=outroot_dir,
                        overwrite=True
                        )

                if this_loop == 'cleanup' and cleanup_cubes:
                    pcp.phangs_cleanup_cubes(
                        gal=gal, array=array, product=product,
                        root_dir=outroot_dir,
                        overwrite=True
                        )