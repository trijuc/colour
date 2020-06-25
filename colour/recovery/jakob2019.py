# -*- coding: utf-8 -*-
"""
Jakob and Hanika (2019) - Reflectance Recovery
==============================================

Defines objects for reflectance recovery using *Jakob and Hanika (2019)*
method:

-   :func:`colour.recovery.RGB_to_sd_Jakob2019`

References
----------
-   :cite:`Jakob2019` : Jakob, W., & Hanika, J. (2019). A Low‐Dimensional
    Function Space for Efficient Spectral Upsampling. Computer Graphics Forum,
    38(2), 147–155. doi:10.1111/cgf.13626
"""

from __future__ import division, unicode_literals

import numpy as np
import struct
from scipy.optimize import minimize
from scipy.interpolate import RegularGridInterpolator

from colour import ILLUMINANT_SDS
from colour.algebra import spow
from colour.colorimetry import (STANDARD_OBSERVER_CMFS, SpectralDistribution,
                                SpectralShape, sd_to_XYZ)
from colour.models import XYZ_to_xy, XYZ_to_Lab, RGB_to_XYZ
from colour.utilities import (as_float_array, runtime_warning,
                              index_along_last_axis)

__author__ = 'Colour Developers'
__copyright__ = 'Copyright (C) 2013-2020 - Colour Developers'
__license__ = 'New BSD License - https://opensource.org/licenses/BSD-3-Clause'
__maintainer__ = 'Colour Developers'
__email__ = 'colour-developers@colour-science.org'
__status__ = 'Production'

__all__ = [
    'DEFAULT_SPECTRAL_SHAPE_JAKOB_2019', 'RGB_to_sd_Jakob2019',
    'Jakob2019Interpolator'
]

DEFAULT_SPECTRAL_SHAPE_JAKOB_2019 = SpectralShape(360, 780, 5)
"""
DEFAULT_SPECTRAL_SHAPE_JAKOB_2019 : SpectralShape
"""


def spectral_model(coefficients,
                   shape=DEFAULT_SPECTRAL_SHAPE_JAKOB_2019,
                   name=None):
    """
    Spectral model given by *Jakob and Hanika (2019)*.
    """

    c_0, c_1, c_2 = coefficients
    wl = shape.range()
    U = c_0 * wl ** 2 + c_1 * wl + c_2
    R = 1 / 2 + U / (2 * np.sqrt(1 + U ** 2))

    if name is None:
        name = "Jakob (2019) - {0} (coeffs.)".format(coefficients)

    return SpectralDistribution(R, wl, name=name)


# The goal is to minimize the color difference between a given distrbution
# and the one computed from the model above.
# This function also calculates the first derivatives with respect to c's.
def error_function(
        coefficients,
        target,
        shape,
        cmfs,
        illuminant,
        illuminant_XYZ,
        return_intermediates=False):
    """
    Computes :math:`\\Delta E_{76}` between the target colour and the
    colour defined by given spectral model, along with its gradient.

    Parameters
    ----------
    coefficients : array_like
        Dimensionless coefficients for *Jakob and Hanika (2019)* reflectance
        spectral model.
    target : array_like, (3,)
        *CIE L\\*a\\*b\\** colourspace array of the target colour.
    shape : SpectralShape
        Spectral distribution shape used in calculations.
    cmfs : XYZ_ColourMatchingFunctions
        Standard observer colour matching functions.
    illuminant : SpectralDistribution
        Illuminant spectral distribution.
    illuminant_XYZ : array_like, (3,)
        *CIE XYZ* tristimulus values of the illuminant.

    Other parameters
    ----------------
    return_intermediates : bool, optional
        If true, some intermediate calculations are returned, for use in
        correctness tests: R, XYZ and Lab

    Returns
    -------
    error : float
        The computed :math:`\\Delta E_{76}` error.
    derror : ndarray, (3,)
        The gradient of error, ie. the first derivatives of error with respect
        to the input coefficients.
    R : ndarray
        Computed spectral reflectance.
    XYZ : ndarray, (3,)
        *CIE XYZ* tristimulus values corresponding to ``R``.
    Lab : ndarray, (3,)
        *CIE L\\*a\\*b\\** colourspace array corresponding to ``XYZ``.
    """

    c_0, c_1, c_2 = coefficients
    wv = np.linspace(0, 1, len(shape.range()))

    U = c_0 * wv ** 2 + c_1 * wv + c_2
    t1 = np.sqrt(1 + U**2)
    R = 1 / 2 + U / (2 * t1)

    t2 = 1 / (2 * t1) - U**2 / (2 * t1**3)
    dR = np.array([wv**2 * t2, wv * t2, t2])

    E = illuminant.values * R
    dE = illuminant.values * dR

    dw = cmfs.wavelengths[1] - cmfs.wavelengths[0]
    k = 1 / (np.sum(cmfs.values[:, 1] * illuminant.values) * dw)

    XYZ = np.empty(3)
    dXYZ = np.empty((3, 3))
    for i in range(3):
        XYZ[i] = k * np.dot(E, cmfs.values[:, i]) * dw
        for j in range(3):
            dXYZ[i, j] = k * np.dot(dE[j], cmfs.values[:, i]) * dw

    XYZ_norm = XYZ / illuminant_XYZ
    f = np.where(
        XYZ_norm > (24 / 116) ** 3,
        spow(XYZ_norm, 1 / 3),
        (841 / 108) * XYZ_norm + 16 / 116,
    )

    # TODO: this can be vectorized
    df = np.empty((3, 3))
    for i in range(3):
        for j in range(3):
            if XYZ_norm[i] > (24 / 116) ** 3:
                df[i, j] = 1 / (3 * spow(illuminant_XYZ[i], 1 / 3)
                                * spow(XYZ[i], 2 / 3)) * dXYZ[i, j]
            else:
                df[i, j] = (841 / 108) * dXYZ[i, j] / illuminant_XYZ[i]

    Lab = np.array([
        116 * f[1] - 16,
        500 * (f[0] - f[1]),
        200 * (f[1] - f[2])
    ])

    dLab = np.array([
        116 * df[1],
        500 * (df[0] - df[1]),
        200 * (df[1] - df[2])
    ])

    error = np.sqrt(np.sum((Lab - target)**2))

    derror = np.zeros(3)
    for i in range(3):
        for j in range(3):
            derror[i] += dLab[j, i] * (Lab[j] - target[j])
        derror[i] /= error

    if return_intermediates:
        return error, derror, R, XYZ, Lab
    return error, derror


def dimensionalise_coefficients(coefficients, shape):
    """
    Rescale dimensionless coefficients.

    A nondimensionalised form of the reflectance spectral model is used in
    optimisation. Instead of the usual spectral shape, specified in nanometers,
    it's normalised to the [0, 1] range. A side effect is that computed
    coefficients work only with the normalised range and need to be
    rescaled to regain units and be compatible with standard shapes.

    Parameters
    ----------
    coefficients : array_like, (3,)
        Dimensionless coefficients.
    shape : SpectralShape
        Spectral distribution shape used in calculations.

    Returns
    -------
    ndarray, (3,)
        Dimensionful coefficients, with units of
        :math:`\\frac{1}{\\mathrm{nm}^2}`, :math:`\\frac{1}{\\mathrm{nm}}`
        and 1, respectively.
    """

    cp_0, cp_1, cp_2 = coefficients
    span = shape.end - shape.start

    c_0 = cp_0 / span ** 2
    c_1 = cp_1 / span - 2 * cp_0 * shape.start / span ** 2
    c_2 = (cp_0 * shape.start ** 2 / span ** 2 - cp_1 * shape.start / span
           + cp_2)

    return np.array([c_0, c_1, c_2])


def create_lightness_scale(steps):
    """
    Create a non-linear lightness scale, as described in *Jakob and Hanika
    (2019)*. The spacing between very dark and very bright (and saturated)
    colors is made smaller, because in those regions coefficients tend to
    change rapidly and a finer resolution is needed.
    """

    def smoothstep(x):
        return x ** 2 * (3 - 2 * x)

    linear = np.linspace(0, 1, steps)
    return smoothstep(smoothstep(linear))


def find_coefficients(
        target_RGB,
        colourspace,
        cmfs=STANDARD_OBSERVER_CMFS['CIE 1931 2 Degree Standard Observer']
        .copy().align(DEFAULT_SPECTRAL_SHAPE_JAKOB_2019),
        illuminant=ILLUMINANT_SDS['D65'].copy().align(
            DEFAULT_SPECTRAL_SHAPE_JAKOB_2019),
        coefficients_0=(0, 0, 0),
        dimensionalise=True,
        use_feedback=True,
        lightness_steps=64):
    """
    Computes coefficients for *Jakob and Hanika (2019)* reflectance spectral
    model.

    Parameters
    ----------
    target_RGB : array_like, (3,)
        *RGB* colourspace array of the target colour. Values must be linear;
        do not apply cctf encoding.
    colourspace : RGB_Colourspace
        The RGB colourspace.
    cmfs : XYZ_ColourMatchingFunctions
        Standard observer colour matching functions.
    illuminant : SpectralDistribution
        Illuminant spectral distribution.
    coefficients_0 : array_like, (3,), optional
        Starting coefficients for the solver.
    use_feedback : bool, optional
        See the documentation for :func:`RGB_to_sd_Jakob2019`.

    Other parameters
    ----------------
    return_intermediates : bool, optional
        If true, some intermediate calculations are returned, for use in
        correctness tests: R, XYZ and Lab
    lightness_steps : int, optional
        See the documentation for :func:`RGB_to_sd_Jakob2019`.

    Returns
    -------
    coefficients : ndarray, (3,)
        Computed coefficients that best fit the given colour.
    error : float
        :math:`\\Delta E_{76}` between the target colour and the colour
        corresponding to the computed coefficients.
    """

    if illuminant.shape != cmfs.shape:
        runtime_warning(
            'Aligning "{0}" illuminant shape to "{1}" colour matching '
            'functions shape.'.format(illuminant.name, cmfs.name))
        illuminant = illuminant.copy().align(cmfs.shape)

    shape = illuminant.shape
    illuminant_XYZ = sd_to_XYZ(illuminant)
    illuminant_XYZ /= illuminant_XYZ[1]
    illuminant_xy = XYZ_to_xy(illuminant_XYZ)

    def RGB_to_Lab(RGB):
        """
        A shorthand for converting from *RGB* to *CIE Lab*.
        """
        XYZ = RGB_to_XYZ(
            RGB,
            colourspace.whitepoint,
            illuminant_xy,
            colourspace.RGB_to_XYZ_matrix,
        )
        return XYZ_to_Lab(XYZ, illuminant_xy)

    if use_feedback:
        target_max = np.max(target_RGB) + 1e-10
        scale = create_lightness_scale(lightness_steps)

        i = lightness_steps // 3
        going_up = scale[i] < np.max(target_RGB)
        while True:
            if going_up:
                if i + 1 == lightness_steps or scale[i + 1] >= target_max:
                    break
            else:
                if i == 0 or scale[i - 1] <= target_max:
                    break

            intermediate_RGB = scale[i] * (target_RGB + 1e-10) / target_max
            intermediate = RGB_to_Lab(intermediate_RGB)

            opt = minimize(
                error_function,
                coefficients_0,
                (intermediate, shape, cmfs, illuminant, illuminant_XYZ),
                method="L-BFGS-B",
                jac=True,
            )
            coefficients_0 = opt.x

            i += 1 if going_up else -1

    target = RGB_to_Lab(target_RGB)
    opt = minimize(
        error_function,
        coefficients_0,
        (target, shape, cmfs, illuminant, illuminant_XYZ),
        method="L-BFGS-B",
        jac=True,
    )

    if dimensionalise:
        coefficients = dimensionalise_coefficients(opt.x, shape)
    else:
        coefficients = opt.x

    return coefficients, opt.fun


def RGB_to_sd_Jakob2019(
        target_RGB,
        colourspace,
        cmfs=STANDARD_OBSERVER_CMFS['CIE 1931 2 Degree Standard Observer']
        .copy().align(DEFAULT_SPECTRAL_SHAPE_JAKOB_2019),
        illuminant=ILLUMINANT_SDS['D65'].copy().align(
            DEFAULT_SPECTRAL_SHAPE_JAKOB_2019),
        return_error=False,
        use_feedback=True,
        lightness_steps=64):
    """
    Recovers the spectral distribution of given RGB colourspace array
    using *Jakob and Hanika (2019)* method.

    Parameters
    ----------
    target_RGB : array_like, (3,)
        *RGB* colourspace array of the target colour. Values must be linear;
        do not apply cctf encoding.
    colourspace : RGB_Colourspace
        The *RGB* colourspace.
    cmfs : XYZ_ColourMatchingFunctions
        Standard observer colour matching functions.
    illuminant : SpectralDistribution
        Illuminant spectral distribution.
    return_error : bool, optional
        If true, ``error`` will be returned alongside ``sd``.
    use_feedback : bool, optional
        If true (the default), a slightly saturated version of the target color
        is solved for first. Then, colors closer and closer to the target are
        computed, feeding the result of every iteration to the next (as
        starting coefficients). This improves stability of results and can
        help if the solver diverges.

    Other parameters
    ----------------
    lightness_steps : int, optional
        The numbers of steps in the lightness scale used for computing
        intermediate colours when ``use_feedback`` is enabled. The default
        value of 64 is what is used in *Jakob and Hanika (2019)*.

    Returns
    -------
    sd : SpectralDistribution
        Recovered spectral distribution.
    error : float
        :math:`\\Delta E_{76}` between the target colour and the colour
        corresponding to the computed coefficients.
    """

    target_RGB = as_float_array(target_RGB)

    coefficients, error = find_coefficients(
        target_RGB,
        colourspace,
        cmfs,
        illuminant
    )

    sd = spectral_model(
        coefficients,
        cmfs.shape,
        name='Jakob (2019) - {0} {1}'.format(colourspace.name, target_RGB)
    )

    if return_error:
        return sd, error
    return sd


class Jakob2019Interpolator:
    def __init__(self):
        pass

    def from_file(self, path):
        with open(path, 'rb') as fd:
            if fd.read(4).decode('ISO-8859-1') != 'SPEC':
                raise ValueError(
                    'Bad magic number, this likely is not the right file type!'
                )

            self.res = struct.unpack('i', fd.read(4))[0]
            self.scale = np.fromfile(fd, count=self.res, dtype=np.float32)
            coeffs = np.fromfile(
                fd, count=3 * self.res ** 3 * 3, dtype=np.float32)
            coeffs = coeffs.reshape(3, self.res, self.res, self.res, 3)

        samples = np.linspace(0, 1, self.res)
        axes = ([0, 1, 2], self.scale, samples, samples)
        self.cubes = RegularGridInterpolator(
            axes, coeffs[:, :, :, :, :], bounds_error=False)

    def coefficients(self, RGB):
        RGB = as_float_array(RGB)

        vmax = np.max(RGB, axis=-1)
        chroma = RGB / (np.expand_dims(vmax, -1) + 1e-10)

        imax = np.argmax(RGB, axis=-1)
        v1 = index_along_last_axis(RGB, imax)
        v2 = index_along_last_axis(chroma, (imax + 2) % 3)
        v3 = index_along_last_axis(chroma, (imax + 1) % 3)

        coords = np.stack([imax, v1, v2, v3], axis=-1)
        return self.cubes(coords).squeeze()

    def RGB_to_sd(self, RGB, shape=DEFAULT_SPECTRAL_SHAPE_JAKOB_2019):
        return spectral_model(
            self.coefficients(RGB),
            shape,
            name='Jakob (2019) - {0} (RGB)'.format(RGB))