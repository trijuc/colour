# -*- coding: utf-8 -*-
"""
Defines unit tests for :mod:`colour.recovery.mallett2019` module.
"""

from __future__ import division, unicode_literals

import unittest
import numpy as np

from colour.characterisation import SDS_COLOURCHECKERS
from colour.colorimetry import (SpectralShape, MSDS_CMFS_STANDARD_OBSERVER,
                                SDS_ILLUMINANTS, CCS_ILLUMINANTS, sd_to_XYZ)
from colour.difference import JND_CIE1976, delta_E_CIE1976
from colour.models import RGB_COLOURSPACE_sRGB, XYZ_to_RGB, XYZ_to_Lab
from colour.recovery import (spectral_primary_decomposition_Mallett2019,
                             RGB_to_sd_Mallett2019, sRGB_to_sd_Mallett2019)

__author__ = 'Colour Developers'
__copyright__ = 'Copyright (C) 2013-2020 - Colour Developers'
__license__ = 'New BSD License - https://opensource.org/licenses/BSD-3-Clause'
__maintainer__ = 'Colour Developers'
__email__ = 'colour-developers@colour-science.org'
__status__ = 'Production'

__all__ = [
    'TestSpectralPrimaryDecompositionMallett2019', 'TestsRGB_to_sd_Mallett2019'
]

SD_D65 = SDS_ILLUMINANTS['D65']
CCS_D65 = CCS_ILLUMINANTS['CIE 1931 2 Degree Standard Observer']['D65']


class TestMixinMallett2019(object):
    """
    A mixin for testing the :mod:`colour.recovery.mallett2019` module.
    """

    def check_callable(self, RGB_to_sd_callable, *args):
        """
        Tests :func:`colour.recovery.RGB_to_sd_Mallett2019` definition or the
        more specialised :func:`colour.recovery.sRGB_to_sd_Mallett2019`
        definition.
        """

        # Make sure the white point is reconstructed as a perfectly flat
        # spectrum.
        RGB = np.full(3, 1.0)
        sd = RGB_to_sd_callable(RGB, *args)
        self.assertLess(np.var(sd.values), 1e-5)

        # Check if the primaries or their combination exceeds the [0, 1] range.
        lower = np.zeros_like(sd.values) - 1e-12
        upper = np.ones_like(sd.values) + 1e+12
        for RGB in [[1, 1, 1], [1, 0, 0], [0, 1, 0], [0, 0, 1]]:
            sd = RGB_to_sd_callable(RGB, *args)
            np.testing.assert_array_less(sd.values, upper)
            np.testing.assert_array_less(lower, sd.values)

        # Check Delta E's using a colour checker.
        for name, sd in SDS_COLOURCHECKERS['ColorChecker N Ohta'].items():
            XYZ = sd_to_XYZ(sd, illuminant=SD_D65) / 100
            Lab = XYZ_to_Lab(XYZ, CCS_D65)
            RGB = XYZ_to_RGB(XYZ, RGB_COLOURSPACE_sRGB.whitepoint, CCS_D65,
                             RGB_COLOURSPACE_sRGB.XYZ_to_RGB_matrix)

            recovered_sd = RGB_to_sd_callable(RGB, *args)
            recovered_XYZ = sd_to_XYZ(recovered_sd, illuminant=SD_D65) / 100
            recovered_Lab = XYZ_to_Lab(recovered_XYZ, CCS_D65)

            error = delta_E_CIE1976(Lab, recovered_Lab)

            # This method has relatively high Delta E's using datasets
            # generated quickly, so the threshold is increased for unit tests.
            if error > 5 * JND_CIE1976:
                self.fail('Delta E for \'{0}\' is {1}!'.format(name, error))


class TestSpectralPrimaryDecompositionMallett2019(unittest.TestCase,
                                                  TestMixinMallett2019):
    """
    Defines :func:`colour.recovery.spectral_primary_decomposition_Mallett2019`
    definition unit tests methods.
    """

    def test_spectral_primary_decomposition_Mallett2019(self):
        """
        Tests :func:`colour.recovery.\
test_spectral_primary_decomposition_Mallett2019` definition.
        """

        shape = SpectralShape(380, 730, 10)
        cmfs = MSDS_CMFS_STANDARD_OBSERVER[
            'CIE 1931 2 Degree Standard Observer']
        cmfs = cmfs.copy().align(shape)
        illuminant = SD_D65.copy().align(shape)

        basis = spectral_primary_decomposition_Mallett2019(
            RGB_COLOURSPACE_sRGB, cmfs, illuminant)

        self.check_callable(RGB_to_sd_Mallett2019, basis)


class TestsRGB_to_sd_Mallett2019(unittest.TestCase, TestMixinMallett2019):
    """
    Defines :func:`colour.recovery.sRGB_to_sd_Mallett2019` definition unit
    tests methods.
    """

    def test_sRGB_to_sd_Mallett2019(self):
        """
        Tests :func:`colour.recovery.sRGB_to_sd_Mallett2019` definition.
        """

        self.check_callable(sRGB_to_sd_Mallett2019)


if __name__ == '__main__':
    unittest.main()
