import numpy as np
import regions
from spectral_cube.spectral_cube import _regionlist_to_single_region
from spectral_cube import SpectralCube
from astropy.table import Table
from astropy import units as u
from astropy.io import fits
from astropy import coordinates
from astropy import wcs
from reproject import reproject_interp
from reproject.mosaicking import find_optimal_celestial_wcs, reproject_and_coadd

basepath = '/orange/adamginsburg/ACES/'

# target_wcs = wcs.WCS(naxis=2)
# target_wcs.wcs.ctype = ['GLON-CAR', 'GLAT-CAR']
# target_wcs.wcs.crval = [0, 0]
# target_wcs.wcs.cunit = ['deg', 'deg']
# target_wcs.wcs.cdelt = [-6.38888888888888e-4, 6.388888888888888e-4]
# target_wcs.wcs.crpix = [2000, 2000]
# 
# header = target_wcs.to_header()
# header['NAXIS1'] = 4000
# header['NAXIS2'] = 4000

import glob

def read_as_2d(fn):
    fh = fits.open(fn)
    fh[0].data = fh[0].data.squeeze()
    ww = wcs.WCS(fh[0].header).celestial
    fh[0].header = ww.to_header()
    return fh


def get_peak(fn, slab_kwargs=None, rest_value=None):
    cube = SpectralCube.read(fn, use_dask=True).with_spectral_unit(u.km/u.s, velocity_convention='radio', rest_value=rest_value)
    if slab_kwargs is not None:
        cube = cube.spectral_slab(**slab_kwargs)
    mx = cube.max(axis=0).to(u.K)
    return mx


def get_m0(fn, slab_kwargs=None, rest_value=None):
    cube = SpectralCube.read(fn, use_dask=True).with_spectral_unit(u.km/u.s, velocity_convention='radio', rest_value=rest_value)
    if slab_kwargs is not None:
        cube = cube.spectral_slab(**slab_kwargs)
    moment0 = cube.moment0(axis=0)
    moment0 = (moment0 * u.s/u.km).to(u.K,
            equivalencies=cube.beam.jtok_equiv(cube.with_spectral_unit(u.GHz).spectral_axis.mean())) * u.km/u.s
    return moment0


def make_mosaic(twod_hdus, name, norm_kwargs={}, slab_kwargs=None, rest_value=None, cb_unit=None):

    target_wcs, shape_out = find_optimal_celestial_wcs(twod_hdus, frame='galactic')

    array, footprint = reproject_and_coadd(hdus,
                                           target_wcs, shape_out=shape_out,
                                           reproject_function=reproject_interp)

    fits.PrimaryHDU(data=array, header=target_wcs.to_header()).writeto(f'{basepath}/mosaics/7m_{name}_mosaic.fits', overwrite=True)

    import pylab as pl
    from astropy import visualization
    pl.rc('axes', axisbelow=True)
    pl.matplotlib.use('agg')

    front = 10
    back = -10
    fronter = 20

    fig = pl.figure(figsize=(20,7))
    ax = fig.add_subplot(111, projection=target_wcs)
    im = ax.imshow(array, norm=visualization.simple_norm(array, **norm_kwargs), zorder=front, cmap='gray')
    cb = pl.colorbar(mappable=im)
    if cb_unit is not None:
        cb.set_label(cb_unit)
    ax.coords[0].set_axislabel('Galactic Longitude')
    ax.coords[1].set_axislabel('Galactic Latitude')
    ax.coords[0].set_major_formatter('d.dd')
    ax.coords[1].set_major_formatter('d.dd')
    ax.coords[0].set_ticks(spacing=0.1*u.deg)
    ax.coords[0].set_ticklabel(rotation=45, pad=20)


    fig.savefig(f'{basepath}/mosaics/7m_{name}_mosaic.png', bbox_inches='tight')

    ax.coords.grid(True, color='black', ls='--', zorder=back)

    overlay = ax.get_coords_overlay('icrs')
    overlay.grid(color='black', ls=':', zorder=back)
    overlay[0].set_axislabel('Right Ascension (ICRS)')
    overlay[1].set_axislabel('Declination (ICRS)')
    overlay[0].set_major_formatter('hh:mm')
    ax.set_axisbelow(True)
    ax.set_zorder(back)
    fig.savefig(f'{basepath}/mosaics/7m_{name}_mosaic_withgrid.png', bbox_inches='tight')



    tbl = Table.read(f'{basepath}/reduction_ACES/SB_naming.tsv', format='ascii.csv', delimiter='\t')

    # create a list of composite regions for labeling purposes
    composites = []
    flagmap = np.zeros(array.shape, dtype='int')
    # loop over the SB_naming table
    for row in tbl:
        indx = row['Proposal ID'][3:]

        # load up regions
        regs = regions.Regions.read(f'{basepath}/reduction_ACES/regions/final_cmz{indx}.reg')
        pregs = [reg.to_pixel(target_wcs) for reg in regs]

        composite = _regionlist_to_single_region(pregs)
        composite.meta['label'] = indx
        composites.append(composite)

        for comp in composites:
            cmsk = comp.to_mask()

            slcs_big, slcs_small = cmsk.get_overlap_slices(array.shape)
            flagmap[slcs_big] += (cmsk.data[slcs_small] * int(comp.meta['label'])) * (flagmap[slcs_big] == 0)



    ax.contour(flagmap, cmap='prism', levels=np.arange(flagmap.max())+0.5, zorder=fronter)

    for ii in np.unique(flagmap):
        if ii > 0:
            fsum = (flagmap==ii).sum()
            cy,cx = ((np.arange(flagmap.shape[0])[:,None] * (flagmap==ii)).sum() / fsum,
                     (np.arange(flagmap.shape[1])[None,:] * (flagmap==ii)).sum() / fsum)
            pl.text(cx, cy, f"{ii}\n{tbl[ii-1]['Obs ID']}",
                    horizontalalignment='left', verticalalignment='center',
                    color=(1,0.8,0.5), transform=ax.get_transform('pixel'),
                    zorder=fronter)

    fig.savefig(f'{basepath}/mosaics/7m_{name}_mosaic_withgridandlabels.png', bbox_inches='tight')

if __name__ == "__main__":

    filelist = glob.glob(f'{basepath}/rawdata/2021.1.00172.L/s*/g*/m*/product/*16_18_20_22*cont.I.tt0.pbcor.fits')
    hdus = [read_as_2d(fn) for fn in filelist]
    make_mosaic(hdus, name='continuum', norm_kwargs=dict(stretch='asinh',
        max_cut=0.2, min_cut=-0.025), cb_unit='Jy/beam')

    filelist = glob.glob(f'{basepath}/rawdata/2021.1.00172.L/s*/g*/m*/product/*spw20.cube.I.pbcor.fits')
    hdus = [get_peak(fn).hdu for fn in filelist]
    make_mosaic(hdus, name='hcop_max', cb_unit='K')
    hdus = [get_m0(fn).hdu for fn in filelist]
    make_mosaic(hdus, name='hcop_m0', cb_unit='K km/s')

    filelist = glob.glob(f'{basepath}/rawdata/2021.1.00172.L/s*/g*/m*/product/*spw22.cube.I.pbcor.fits')
    hdus = [get_peak(fn).hdu for fn in filelist]
    make_mosaic(hdus, name='hnco_max')
    hdus = [get_m0(fn).hdu for fn in filelist]
    make_mosaic(hdus, name='hnco_m0', cb_unit='K km/s')



    filelist = glob.glob(f'{basepath}/rawdata/2021.1.00172.L/s*/g*/m*/product/*spw24.cube.I.pbcor.fits')
    hdus = [get_peak(fn, slab_kwargs={'lo':-200*u.km/u.s, 'hi':200*u.km/u.s}, rest_value=99.02295*u.GHz).hdu for fn in filelist]
    make_mosaic(hdus, name='h40a_max', cb_unit='K', norm_kwargs=dict(max_cut=0.5, min_cut=-0.01, stretch='asinh'))
    hdus = [get_m0(fn, slab_kwargs={'lo':-200*u.km/u.s, 'hi':200*u.km/u.s}, rest_value=99.02295*u.GHz).hdu for fn in filelist]
    make_mosaic(hdus, name='h40a_m0', cb_unit='K km/s', norm_kwargs={'max_cut': 20, 'min_cut':-1, 'stretch':'asinh'})
