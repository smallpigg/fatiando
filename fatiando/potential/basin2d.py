# Copyright 2012 The Fatiando a Terra Development Team
#
# This file is part of Fatiando a Terra.
#
# Fatiando a Terra is free software: you can redistribute it and/or modify
# it under the terms of the GNU Lesser General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# Fatiando a Terra is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public License
# along with Fatiando a Terra.  If not, see <http://www.gnu.org/licenses/>.
"""
Estimate the basement relief of two-dimensional basins from potential field
data.

**POLYGONAL PARAMETRIZATION**

* :func:`fatiando.potential.basin2d.triangular`
* :func:`fatiando.potential.basin2d.trapezoidal`

Uses 2D bodies with a polygonal cross-section to parameterize the basin relief.
Potential fields are calculated using the :mod:`fatiando.potential.talwani`
module. 

Example of triagular basin inversion using synthetic data::

    >>> import numpy
    >>> from fatiando.mesher.dd import Polygon
    >>> from fatiando.potential import talwani
    >>> from fatiando.inversion.gradient import steepest
    >>> from fatiando import logger
    >>> log = logger.get()
    >>> # Make a triangular basin model (will estimate the last point)
    >>> verts = [(10000, 100), (90000, 100), (50000, 5000)]
    >>> left, middle, right = verts
    >>> props = {'density':500}
    >>> model = Polygon(verts, props)
    >>> # Generate the synthetic gz profile
    >>> xs = numpy.arange(0, 100000, 10000)
    >>> zs = numpy.zeros_like(xs)
    >>> gz = talwani.gz(xs, zs, [model])
    >>> # Pack the data nicely in a DataModule
    >>> dm = TriangularGzDM(xs, zs, gz, prop=500, verts=[left, middle])
    >>> # Estimate the coordinates of the last point using Steepest Descent
    >>> solver = steepest(initial=(10000, 1000))
    >>> p, res = triangular([dm], solver)
    >>> for v in p:
    ...     print '%.1f' % (v),
    50000. 5000.
    >>> print gz
    


**PRISMATIC PARAMETRIZATION**

* :func:`fatiando.potential.basin2d.prism`
 
Uses juxtaposed 2D right rectangular prisms to parameterize the basin relief.
Potential fields are calculated using the :mod:`fatiando.potential.prism2d`
module. 

----

"""
__author__ = 'Leonardo Uieda (leouieda@gmail.com)'
__date__ = 'Created 29-Jan-2012'

import time
import numpy

from fatiando.potential import _talwani
from fatiando import inversion, utils, logger

log = logger.dummy()


class TriangularGzDM(inversion.datamodule.DataModule):
    """
    Data module for the inversion to estimate the relief of a triangular basin.

    Packs the necessary data and interpretative model information.

    The forward modeling is done using :mod:`fatiando.potential.talwani`.
    Derivatives are calculated using a 2-point finite difference approximation.
    The Hessian matrix is calculated using a Gauss-Newton approximation.

    Parameters:

    * xp, zp
        Arrays with the x and z coordinates of the profile data points
    * data
        Array with the profile data
    * verts
        List with the (x, z) coordinates of the two know vertices. Very
        important that the vertices in the list be ordered from left to right!
        Otherwise the forward model will give results with an inverted sign and
        terrible things may happen!
    * prop
        Value of the physical property of the basin. The physical property must
        be compatible with the potential field used! I.e., gravitational fields
        require a value of density contrast.
    * delta
        Interval used to calculate the approximate derivatives
        
    """

    def __init__(self, xp, zp, data, verts, prop, delta=1.):
        inversion.datamodule.DataModule.__init__(self, data)
        log.info("Initializing TriangularDM data module:")
        if len(xp) != len(zp) != len(data):
            raise ValueError, "xp, zp, and data must be of same length"
        if len(verts) != 2:
            raise ValueError, "Need exactly 2 vertices. %d given" % (len(verts))
        self.xp = numpy.array(xp, dtype=numpy.float64)
        self.zp = numpy.array(zp, dtype=numpy.float64)
        self.prop = float(prop)
        self.verts = verts
        self.delta = numpy.array([0., 0., delta], dtype='f')
        log.info("  number of data: %d" % (len(data)))
        log.info("  physical property: %s" % (str(prop)))
        
    def get_predicted(self, p):
        tmp = [v for v in self.verts]
        tmp.append(p)
        xs, zs = numpy.array(tmp, dtype='f').T
        return _talwani.talwani_gz(self.prop, xs, zs, self.xp, self.zp)

    def sum_gradient(self, gradient, p, residuals):
        xp, zp = self.xp, self.zp
        delta = self.delta
        tmp = [v for v in self.verts]
        tmp.append(p)
        xs, zs = numpy.array(tmp, dtype='f').T
        at_p = _talwani.talwani_gz(self.prop, xs, zs, xp, zp)
        jacx = ((_talwani.talwani_gz(self.prop, xs + delta, zs, xp, zp) - at_p)/
                delta[-1])
        jacz = ((_talwani.talwani_gz(self.prop, xs, zs + delta, xp, zp) - at_p)/
                delta[-1])
        self.jac_T = numpy.array([jacx, jacz])
        return gradient - 2.*numpy.dot(self.jac_T, residuals)

    def sum_hessian(self, hessian, p):
        return hessian + 2*numpy.dot(self.jac_T, self.jac_T.T)

def triangular(dms, solver, iterate=False):
    """
    Estimate basement relief of a triangular basin. The basin is modeled as a
    triangle with two known vertices at the surface. The parameters estimated
    are the x and z coordinates of the third vertice.

    Parameters:

    * dms
        List of data modules, like
        :class:`fatiando.potential.basin2d.TriangularGzDM`
    * solver
        A non-linear inverse problem solver generated by a factory function
        from a :mod:`fatiando.inversion` inverse problem solver module.
    * iterate
        If True, will yield the current estimate at each iteration yielded by
        *solver*. In Python terms, ``iterate=True`` transforms this function
        into a generator function.
        
    Returns:

    * [estimate, residuals]
        The estimated (x, z) coordinates of the missing vertice and a list of
        the residuals (difference between measured and predicted data) for each
        data module in *dms*
    
    """
    log.info("Estimating relief of a triangular basin:")
    log.info("  iterate: %s" % (str(iterate)))
    if iterate:
        return _triangular_iterator(dms, solver)
    else:
        return _triangular_solver(dms, solver)

def _triangular_solver(dms, solver):
    start = time.time()
    try:
        for i, chset in enumerate(solver(dms, [])):
            continue
    except numpy.linalg.linalg.LinAlgError:
        raise ValueError, ("Oops, the Hessian is a singular matrix." +
                           " Try applying more regularization")
    stop = time.time()
    log.info("  number of iterations: %d" % (i))
    log.info("  final data misfit: %g" % (chset['misfits'][-1]))
    log.info("  final goal function: %g" % (chset['goals'][-1]))
    log.info("  time: %s" % (utils.sec2hms(stop - start)))
    return chset['estimate'], chset['residuals']

def _triangular_iterator(dms, solver):
    start = time.time()
    try:
        for i, chset in enumerate(solver(dms, [])):
            yield chset['estimate'], chset['residuals']
    except numpy.linalg.linalg.LinAlgError:
        raise ValueError, ("Oops, the Hessian is a singular matrix." +
                           " Try applying more regularization")
    stop = time.time()
    log.info("  number of iterations: %d" % (i))
    log.info("  final data misfit: %g" % (chset['misfits'][-1]))
    log.info("  final goal function: %g" % (chset['goals'][-1]))
    log.info("  time: %s" % (utils.sec2hms(stop - start)))    

def trapezoidal():
    pass
    
def prism():
    pass
            
def _test():
    import doctest
    doctest.testmod()
    print "doctest finished"

if __name__ == '__main__':
    _test()
    
