"""
Standalone routines related to linear mosaicking of multi-part mosaics
in CASA.
"""

#region Imports and definitions

import os
import numpy as np
import pyfits # CASA has pyfits, not astropy
import glob

import logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

# Analysis utilities
import analysisUtils as au

# CASA stuff
import casaStuff as casa

# Other pipeline stuff
import casaMaskingRoutines as cma

# Pipeline versionining
from pipelineVersion import version as pipeVer

#endregion

#region Routines to match resolution

def common_res_for_mosaic(
    infile_list = None, 
    outfile_list = None,
    target_res=None,
    pixel_padding=2.0,
    do_convolve=True,
    overwrite=False
    ):
    """
    Convolve multi-part cubes to a common res for mosaicking. 

    infile_list : list of input files.

    outfile_list : if do_convolve is true, a list of output files that
    will get the convolved data. Can be a dictionary or a list. If
    it's a list then matching is by order, so that firs infile goes to
    first outfile, etc. If it's a dictionary, it looks for the infile
    name as a key.

    target_res : force this target resolution.

    pixel_padding (default 2.0) : the number of pixels to add to the
    largest common beam (in quadrature) to ensure robust convolution.

    do_convolve (default True) : do the convolution. Otherwise just
    calculates and returns the target resolution.

    overwrite (default False) : Delete existing files. You probably
    want to set this to True but it's a user decision.

    Unless a target resolution is supplied, the routine first
    calculates the common resolution based on the beam size of all of
    the input files. This target resolution is returned as the output
    of the routine. The supplied pixel_padding is used to ensure that
    a convolution kernel can be built by imregrid, since CASA can't
    currently keep the major axis fixed and convolve the minor axis.

    If do_convolve is True, it also convolves all of the input files
    to output files with that resolution. For this it needs a list of
    output files matched to the input file list, either as another
    list or a dictionary.
    """
    
    # Check inputs.

    # First check that input files are supplied and exist.

    if infile_list is None:
        logger.error("Missing required infile_list.")
        return(None)   
    
    for this_file in infile_list:
        if os.path.isdir(this_file) == False:
            logger.error("File not found "+this_file)
            return(None)
    
    # If do_convolve is True then make sure that we have output files
    # and that they match the input files.

    if do_convolve:

        if outfile_list is None:
            logger.error("Missing outfile_list required for convolution.")
            return(None)

        if (type(outfile_list) != type([])) and (type(outfile_list) != type({})):
            logger.error("outfile_list must be dictionary or list.")
            return(None)

        if type(outfile_list) == type([]):
            if len(infile_list) != len(outfile_list):
                logger.error("Mismatch in input and output list lengths.")
                return(None)
            outfile_dict = {}
            for ii in range(len(infile_list)):
                outfile_dict[infile_list[ii]] = outfile_list[ii]

        if type(outfile_list) == type({}):
            outfile_dict = outfile_list

        missing_keys = 0
        for infile in infile_list:
            if infile not in outfile_dict.keys():
                logger.error("Missing output file for infile: "+infile)
                missing_keys += 1
            if missing_keys > 0:
                logger.error("Missing "+str(missing_keys)+" output file names.")
                return(None)

    # Figure out the target resolution if it is not supplied by the user

    if target_res is None:
        logger.debug("Calculating target resolution ... ")

        bmaj_list = []
        pix_list = []

        for this_infile in infile_list:
            logger.info("Checking "+this_infile)

            hdr = casa.imhead(this_infile)

            if (hdr['axisunits'][0] != 'rad'):
                logger.error("ERROR: Based on CASA experience. I expected units of radians.")
                logger.error("I did not find this. Returning. Adjust code or investigate file "+this_infile)
                return(None)
            this_pixel = abs(hdr['incr'][0]/np.pi*180.0*3600.)

            if (hdr['restoringbeam']['major']['unit'] != 'arcsec'):
                logger.error("ERROR: Based on CASA experience. I expected units of arcseconds for the beam.")
                logger.error("I did not find this. Returning. Adjust code or investigate file "+this_infile)
                return(None)
            this_bmaj = hdr['restoringbeam']['major']['value']

            bmaj_list.append(this_bmaj)
            pix_list.append(this_pixel)
        
        max_bmaj = np.max(bmaj_list)
        max_pix = np.max(pix_list)
        target_bmaj = np.sqrt((max_bmaj)**2+(pixel_padding*max_pix)**2)
    else:
        target_bmaj = force_beam

    if not do_convolve:
        return(target_bmaj)

    # With a target resolution and matched lists we can proceed.

    for this_infile in infile_list:
        this_outfile = outfile_dict[this_infile]
        logger.debug("Convolving "+this_infile+' to '+this_outfile)
        
        casa.imsmooth(imagename=this_infile,
                      outfile=this_outfile,
                      targetres=True,
                      major=str(target_bmaj)+'arcsec',
                      minor=str(target_bmaj)+'arcsec',
                      pa='0.0deg',
                      overwrite=overwrite
                      )

    return(target_bmaj)

#endregion

#region Routines to match astrometry between parts of a mosaic

def calculate_mosaic_extent(
    infile_list = None, 
    force_ra_ctr = None, 
    force_dec_ctr = None,
    ):
    """
    Given a list of input files, calculate the center and extent of
    the mosaic needed to cover them all. Return the results as a
    dictionary.

    infile_list : list of input files to loop over.

    force_ra_ctr (default None) : if set then force the RA center of
    the mosaic to be this value, and the returned extent is the
    largest separation of any image corner from this value in RA.

    force_dec_ctr (default None) : as force_ra_ctr but for
    Declination.

    If the RA and Dec. centers are supplied, then they are assumed to
    be in decimal degrees.
    """

    # Check inputs

    if infile_list is None:
        logger.error("Missing required infile_list.")
        return(None)

    for this_infile in infile_list:
        if not os.path.isdir(this_infile):
            logger.error("File not found "+this_infile+"Returning.")
            return(None)

    # Initialize the list of corner RA and Dec positions.

    ra_list = []
    dec_list = []

    # TBD - right now we assume matched frequency/velocity axis
    freq_list = []

    # Loop over input files and calculate RA and Dec coordinates of
    # the corners.

    for this_infile in infile_list:

        this_hdr = casa.imhead(this_infile)

        if this_hdr['axisnames'][0] != 'Right Ascension':
            logger.error("Expected axis 0 to be Right Ascension. Returning.")
            return(None)
        if this_hdr['axisunits'][0] != 'rad':
            logger.error("Expected axis units to be radians. Returning.")
            return(None)
        if this_hdr['axisnames'][1] != 'Declination':
            logger.error("Expected axis 1 to be Declination. Returning.")
            return(None)
        if this_hdr['axisunits'][1] != 'rad':
            logger.error("Expected axis units to be radians. Returning.")
            return(None)

        this_shape = this_hdr['shape']
        xlo = 0
        xhi = this_shape[0]-1
        ylo = 0
        yhi = this_shape[1]-1

        pixbox = str(xlo)+','+str(ylo)+','+str(xlo)+','+str(ylo)
        blc = imval(this_infile, chans='0', box=pixbox)

        pixbox = str(xlo)+','+str(yhi)+','+str(xlo)+','+str(yhi)
        tlc = imval(this_infile, chans='0', box=pixbox)
        
        pixbox = str(xhi)+','+str(yhi)+','+str(xhi)+','+str(yhi)
        trc = imval(this_infile, chans='0', box=pixbox)

        pixbox = str(xhi)+','+str(ylo)+','+str(xhi)+','+str(ylo)
        brc = imval(this_infile, chans='0', box=pixbox)
        
        ra_list.append(blc['coords'][0][0])
        ra_list.append(tlc['coords'][0][0])
        ra_list.append(trc['coords'][0][0])
        ra_list.append(brc['coords'][0][0])

        dec_list.append(blc['coords'][0][1])
        dec_list.append(tlc['coords'][0][1])
        dec_list.append(trc['coords'][0][1])
        dec_list.append(brc['coords'][0][1])
        
    # Get the minimum and maximum RA and Declination. 

    # TBD - this breaks straddling the meridian (RA = 0) or the poles
    # (Dec = 90). Add catch cases or at least error calls for
    # this. Meridian seems more likely to come up, so just that is
    # probably fine.

    min_ra = np.min(ra_list)
    max_ra = np.max(ra_list)
    min_dec = np.min(dec_list)
    max_dec = np.max(dec_list)

    # TBD - right now we assume matched frequency/velocity axis

    min_freq = None
    max_freq = None

    # If we do not force the center of the mosaic, then take it to be
    # the average of the min and max, so that the image will be a
    # square.

    if force_ra_ctr == None:
        ra_ctr = (max_ra+min_ra)*0.5
    else:
        ra_ctr = force_ra_ctr*np.pi/180.

    if force_dec_ctr == None:
        dec_ctr = (max_dec+min_dec)*0.5
    else:
        dec_ctr = force_dec_ctr*np.pi/180.

    # Now calculate the total extent of the mosaic given the center.

    delta_ra = 2.0*np.max([np.abs(max_ra-ra_ctr),np.abs(min_ra-ra_ctr)])
    delta_ra *= np.cos(dec_ctr)
    delta_dec = 2.0*np.max([np.abs(max_dec-dec_ctr),np.abs(min_dec-dec_ctr)])
    
    # Put the output into a dictionary.

    output = {
        'ra_ctr':[ra_ctr*180./np.pi,'degrees'],
        'dec_ctr':[dec_ctr*180./np.pi,'degrees'],
        'delta_ra':[delta_ra*180./np.pi*3600.,'arcsec'],
        'delta_dec':[delta_dec*180./np.pi*3600.,'arcsec'],
        }

    return(output)

def build_common_header(
    infile_list = None,
    template_file = None,
    ra_ctr = None, 
    dec_ctr = None,
    delta_ra = None, 
    delta_dec = None,
    allow_big_image = False,
    too_big_pix=1e4,
    ):
    """
    Build a target header to be used as a template by imregrid when
    setting up linear mosaicking operations.

    infile_list : the list of input files. Used to generate the
    center, extent, and pick a template file if these things aren't
    supplied by the user.

    template_file : the name of a file to use as the template. The
    coordinate axes and size are manipulated but other things like the
    pixel size and units remain the same. If this is not supplied the
    first file from the input file list is selected.

    ra_ctr : the center of the output file in right ascension. Assumed
    to be in decimal degrees. If None or not supplied, then this is
    calculated from the image stack.

    dec_ctr : as ra_ctr but for declination.

    delta_ra : the extent of the output image in arcseconds. If this
    is not supplied, it is calculated from the image stack.

    delta_dec : as delta_ra but for declination.

    allow_big_image (default False) : allow very big images? If False
    then the program throws an error if the image appears too
    big. This is often the sign of a bug.

    too_big_pix (default 1e4) : definition of pixel scale (in one
    dimension) that marks an image as too big.
    """

    # Check inputs
    
    if template_file is None:

        if infile_list is None:
            logger.error("Missing required infile_list and no template file.")
            return(None)
    
        template_file = infile_list[0]
        logger.info("Using first input file as template - "+template_file)

    if infile_list is not None:
        for this_infile in infile_list:
            if not os.path.isdir(this_infile):
                logger.error("File not found "+this_infile+" . Returning.")
                return(None)

    if template_file is not None:
        if os.path.isdir(template_file) == False:
            logger.error("The specified template file does not exist.")
            return(None)

    if infile_list is None:
        
        if template_file is None:
            logger.error("Without an input file stack, I need a template file.")
            return(None)

        if (delta_ra is None) or (delta_dec is None) or (ra_ctr is None) or (dec_ctr is None):
            logger.error("Without an input file stack, I need ra_ctr, dec_ctr, delta_ra, delta_dec.")
            return(None)

    # If the RA and Dec center and extent are not full specified, then
    # calculate the extent based on the image stack.

    if (delta_ra is None) or (delta_dec is None) or \
            (ra_ctr is None) or (dec_ctr is None):

        logger.info("Extent not fully specified. Calculating it from image stack.")
        extent_dict = calculate_mosaic_extent(
            infile_list = infile_list,
            force_ra_ctr = ra_ctr,
            force_dec_ctr = dec_ctr
            )
        
        if ra_ctr is None:
            ra_ctr = extent['ra_ctr'][0]
        if dec_ctr is None:
            dec_ctr = extent['dec_ctr'][0]
        if delta_ra is None:
            delta_ra = extent['delta_ra'][0]
        if delta_dec is None:
            delta_dec = extent['delta_dec'][0]
        
    # Get the header from the template file

    target_hdr = casa.imregrid(template_file, template='get')
    
    # Get the pixel scale. This makes some assumptions. We could put a
    # lot of general logic here, but we are usually working in a
    # case where this works.

    if (target_hdr['csys']['direction0']['units'][0] != 'rad') or \
            (target_hdr['csys']['direction0']['units'][1] != 'rad'):
        logger.error("ERROR: Based on CASA experience. I expected pixel units of radians.")
        logger.error("I did not find this. Returning. Adjust code or investigate file "+infile_list[0])
        return(None)

    # Add our target center pixel values to the header after
    # converting to radians.

    ra_ctr_in_rad = ra_ctr * np.pi / 180.
    dec_ctr_in_rad = dec_ctr * np.pi / 180.

    target_hdr['csys']['direction0']['crval'][0] = ra_ctr_in_rad
    target_hdr['csys']['direction0']['crval'][1] = dec_ctr_in_rad

    # Calculate the size of the image in pixels and set the central
    # pixel coordinate for the RA and Dec axis.
    
    ra_pix_in_as = np.abs(target_hdr['csys']['direction0']['cdelt'][0]*180./np.pi*3600.)
    ra_axis_size = np.ceil(delta_ra / ra_pix_in_as)
    new_ra_ctr_pix = ra_axis_size/2.0

    dec_pix_in_as = np.abs(target_hdr['csys']['direction0']['cdelt'][1]*180./np.pi*3600.)
    dec_axis_size = np.ceil(delta_dec / dec_pix_in_as)
    new_dec_ctr_pix = dec_axis_size/2.0
    
    # Check that the axis size isn't too big. This is likely to be a
    # bug. If allowbigimage is True then bypass this, otherwise exit.

    if not allow_big_image:
        if ra_axis_size > too_big_pix or \
                dec_axis_size > too_big_pix:
            logger.error("WARNING! This is a very big image you plan to create, "+str(ra_axis_size)+ \
                             " x "+str(dec_axis_size))
            logger.error(" To make an image this big set allowbigimage=True. Returning.")
            return(None)

    # Enter the new values into the header and return.

    target_hdr['csys']['direction0']['crpix'][0] = new_ra_ctr_pix
    target_hdr['csys']['direction0']['crpix'][1] = new_dec_ctr_pix
    
    target_hdr['shap'][0] = int(ra_axis_size)
    target_hdr['shap'][1] = int(dec_axis_size)
    
    return(target_hdr)

def common_astrometry_for_mosaic(
    infile_list = None,
    outfile_list = None,
    target_hdr = None,
    template_file = None,
    # could use **kwargs here if this gets much more complicated
    ra_ctr = None, 
    dec_ctr = None,
    delta_ra = None, 
    delta_dec = None,
    allow_big_image = False,
    too_big_pix=1e4,   
    asvelocity=True,
    interpolation='cubic',
    axes=[-1],
    overwrite=False,
    ):
    """
    Build a common astrometry for a mosaic and align all input image
    files to that astrometry. If the common astrometry isn't supplied
    as a header, the program calls other routines to create it based
    on the supplied parameters and stack of input images. Returns the
    common header.
    
    infile_list : list of input files.

    outfile_list : a list of output files that will get the convolved
    data. Can be a dictionary or a list. If it's a list then matching
    is by order, so that firs infile goes to first outfile, etc. If
    it's a dictionary, it looks for the infile name as a key.

    target_hdr : the CASA-format header used to align the images,
    needs the same format returned by a call to imregrid with
    template='get'.

    ra_ctr, dec_ctr, delta_ra, delta_dec, allow_big_image, too_big_pix
    : keywords passed to the header creation routine. See
    documentation for "build_common_header" to explain these.

    asvelocity, interpolation, axes : keywords passed to the CASA imregrid
    call. See documentation there.

    overwrite (default False) : Delete existing files. You probably
    want to set this to True but it's a user decision.
    """

    # Error checking - mostly the subprograms do this.

    if infile_list is None:
        logger.error("Infile list missing.")
        return(None)

    if outfile_list is None:
        logger.error("Outfile list missing.")
        return(None)

    # Make sure that the outfile list is a dictionary

    if (type(outfile_list) != type([])) and (type(outfile_list) != type({})):
        logger.error("outfile_list must be dictionary or list.")
        return(None)

    if type(outfile_list) == type([]):
        if len(infile_list) != len(outfile_list):
            logger.error("Mismatch in input and output list lengths.")
            return(None)
        outfile_dict = {}
        for ii in range(len(infile_list)):
            outfile_dict[infile_list[ii]] = outfile_list[ii]

    if type(outfile_list) == type({}):
        outfile_dict = outfile_list

    # Get the common header if one is not supplied

    if target_hdr is None:
        
        logger.info('Generating target header.')
        
        target_hdr = build_common_header(
            infile_list = infile_list, 
            template_file = template_file,
            ra_ctr = ra_ctr, 
            dec_ctr = dec_ctr,
            delta_ra = delta_ra, 
            delta_dec = delta_dec,
            allow_big_image = allow_big_image,
            too_big_pix=too_big_pix,
            )

    # Align the input files to the new astrometry. This will also loop
    # over and align any "weight" files.

    logger.info('Aligning image files.')

    for this_infile in infile_list:
        
        this_outfile = outfile_dict[this_infile]

        if os.path.isdir(this_infile) == False:
            logger.error("File "+this_infile+" not found. Continuing.")
            continue

        casa.imregrid(imagename=this_infile,
                      template=target_hdr,
                      output=this_outfile,
                      asvelocity=asvelocity,
                      axes=axes,
                      interpolation=interpolation,
                      overwrite=overwrite)

    return(target_hdr)

#endregion

#region Routines to deal with weighting

def generate_weight_file(
    image_file = None,
    input_file = None,
    input_value = None,    
    input_type = 'pb',
    outfile = None,
    scale_by_noise = False,
    noise_value = None,
    scale_by_factor = None,
    overwrite=False,
    ):
    """
    Generate a weight image for use in a linear mosaic.
    """

    # Check input

    if image_file is None and input_file is None:
        logger.error("I need either an input or an image template file.")
        return(None)

    if input_file is None and input_value is None:
        logger.error("I need either an input value or an input file.")
        return(None)

    if input_file is not None and input_value is not None:
        logger.error("I need ONE OF an input value or an input file. Got both.")
        return(None)

    if outfile is None:
        logger.error("Specify output file.")
        return(None)

    if input_file is not None:
        valid_types = ['pb', 'noise', 'weight']
        if input_type not in valid_types:
            logger.error("Valid input types are :"+str(valid_types))
            return(None)

    if input_file is None and input_value is None:
        logger.error("Need either an input value or an input file.")
        return(None)

    if input_file is not None:
        if not os.path.isdir(input_file):
            logger.error("Missing input file directory - "+input_file)
            return(None)

    if image_file is not None:
        if not os.path.isdir(image_file):
            logger.error("Missing image file directory - "+image_file)
            return(None)

    # If scaling by noise is requested and no estimate is provided,
    # generate an estimate

    if scale_by_noise:

        if noise_value is None and image_file is None:
            logger.error("I can only scale by the noise if I get an image file to caluclate the noise. Returning.")
            return(None)

        if noise_value is None:
            
            pass

    # Define the template for the astrometry

    if input_file is None:
        template = image_file
    else:
        template = input_file

    # Check the output file

    if os.path.isdir(outfile) or os.path.isfile(outfile):
        if not overwrite:
            logger.error("File exists and overwrite set to false - "+outfile)
            return(None)
        os.system('rm -rf '+outfile)

    # Copy the template and read the data into memory

    os.system("cp -r "+template+" "+outfile)

    myia = au.createCasaTool(casa.iatool)
    myia.open(outfile)
    data = myia.getchunk()

    # Case 1 : We just have an input value.

    if input_file is None and input_value is not None:        

        if input_type is 'noise':
            weight_value = 1./input_value**2
        if input_type is 'pb':
            weight_value = input_value**2
        if input_type is 'weight':
            weight_value = input_value

        weight_image = data*0.0 + weight_value
    
    # Case 2 : We have an input image

    if input_file is not None:

        os.system("cp -r "+template+" "+outfile)

        if input_type is 'noise':
            weight_image = 1./data**2
        if input_type is 'pb':
            weight_image = data**2
        if input_type is 'weight':
            weight_image = data

    # If request, scale the data by a factor

    if scale_by_factor is not None:
        
        weight_image = weight_image * scale_by_factor

    # If request, scale the data by the inverse square of the noise estimate.

    if scale_by_noise:

        noise_scale_factor = 1./noise_value**2

    myia.putchunk(data)
    myia.close()

    return(None)
    

#endregion

#region Routines to carry out the mosaicking

def mosaic_aligned_data(
    infile_list = None, 
    weightfile_list = None,
    outfile = None, 
    overwrite=False
    ):
    """
    Combine a list of aligned data with primary-beam (i.e., inverse
    noise) weights using simple linear mosaicking.
    """

    if infile_list is None or \
            weightfile_list is None or \
            outfile is None:
        logger.error("Missing required input.")
        return(None)

    sum_file = outfile+'.sum'
    weight_file = outfile+'.weight'

    if (os.path.isdir(outfile) or \
            os.path.isdir(sum_file) or \
            os.path.isdir(weight_file)) and \
            (overwrite == False):
        logger.error("Output file present and overwrite off. Returning.")
        return(None)

    if overwrite:
        os.system('rm -rf '+outfile+'.temp')
        os.system('rm -rf '+outfile)
        os.system('rm -rf '+sum_file)
        os.system('rm -rf '+weight_file)
        os.system('rm -rf '+outfile+'.mask')

    imlist = infile_list[:]
    imlist.extend(weightfile_list)
    n_image = len(infile_list)
    lel_exp_sum = ''
    lel_exp_weight = ''
    first = True
    for ii in range(n_image):
        this_im = 'IM'+str(ii)
        this_wt = 'IM'+str(ii+n_image)
        this_lel_sum = '('+this_im+'*'+this_wt+'*'+this_wt+')'
        this_lel_weight = '('+this_wt+'*'+this_wt+')'
        if first:
            lel_exp_sum += this_lel_sum
            lel_exp_weight += this_lel_weight
            first=False
        else:
            lel_exp_sum += '+'+this_lel_sum
            lel_exp_weight += '+'+this_lel_weight

    casa.immath(imagename = imlist, mode='evalexpr',
                expr=lel_exp_sum, outfile=sum_file,
                imagemd = imlist[0])
    
    myia = au.createCasaTool(casa.iatool)
    myia.open(sum_file)
    myia.set(pixelmask=1)
    myia.close()

    casa.immath(imagename = imlist, mode='evalexpr',
                expr=lel_exp_weight, outfile=weight_file)
    myia.open(weight_file)
    myia.set(pixelmask=1)
    myia.close()

    casa.immath(imagename = [sum_file, weight_file], mode='evalexpr',
                expr='iif(IM1 > 0.0, IM0/IM1, 0.0)', outfile=outfile+'.temp',
                imagemd = sum_file)

    casa.immath(imagename = weight_file, mode='evalexpr',
                expr='iif(IM0 > 0.0, 1.0, 0.0)', outfile=outfile+'.mask')
    
    casa.imsubimage(imagename=outfile+'.temp', outfile=outfile,
                    mask='"'+outfile+'.mask"', dropdeg=True)

    return(None)

#endregion
