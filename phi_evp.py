import os
path = os.path.dirname(os.path.abspath(__file__))
import sys
import numpy as np
import matplotlib.pyplot as plt
import dedalus.public as d3
from dedalus.core import domain
import logging
logger = logging.getLogger(__name__)
from scipy.optimize import minimize
from natsort import natsorted
from configparser import ConfigParser


def construct_phi(a, delta, dist, coords, bases):

    xbasis, ybasis = bases[1], bases[0]
    ey, ex = coords.unit_vector_fields(dist)
    y, x = ybasis.local_grid(), xbasis.local_grid()
    # y, x = ybasis.global_grid(), xbasis.global_grid()
    y_g = y * np.ones_like(x)
    x_g = x * np.ones_like(y)
    Nx = max(x.shape)
    Ny = max(y.shape)

    #ellipse
    n = len(a)
    ks = list(range(n))
    
    theta = np.pi

    dist_mat = np.zeros((n, n))
    for row in range(n):
        for col in range(n):
            if (row == col):
                dist_mat[row, col] = a[row] * np.conj(a[row])
            elif (col > row):
                dist_mat[row, col] = a[col] * np.conj(a[row]) * np.exp(1j*col*theta)
            else:
                dist_mat[row, col] = np.conj(a[col] * np.conj(a[row]) * np.exp(1j*col*theta))

    print(np.sqrt(np.sum(dist_mat)))
    sys.exit()

    
    # ks = [0]
    # for i in range(2, n + 1):
    #     ks.append((-1)**i * int(i / 2))

        
    thetas = np.linspace(0, 2*np.pi, 1000)

    r = np.zeros(thetas.shape, dtype=np.complex128)
    for i, theta in enumerate(thetas):
        for k, a_k in zip(ks, a):
            r[i] += a_k * np.exp(1j*k*theta)

    rx = r.real
    ry = r.imag
    rs = list(zip(rx, ry))

    logger.info('solving for the signed distance function. This might take a sec')
    from matplotlib import path
    curve = path.Path(rs) 
    # flags = p.contains_points(x_g, y_g)
    enclosed = np.zeros_like(x_g)
    for ix in range(Nx):
        for iy in range(Ny):
            if (curve.contains_points([(x_g[iy, ix], y_g[iy, ix])])):
                enclosed[iy, ix] = 1

    # phi_g = (np.tanh(2*SDF / delta) + 1.0) / 2.0

    return None, rs



filename = path + '/nsvp_options.cfg'
config = ConfigParser()
config.read(str(filename))

# Parameters
Lx, Ly = 10, 2*np.pi
Nx, Ny = 256, 128
dtype = np.float64

Reynolds = config.getfloat('parameters', 'Reynolds')
nu = 1 / Reynolds
U0 = config.getfloat('parameters', 'U0')
tau = config.getfloat('parameters', 'tau')
delta = config.getfloat('parameters', 'delta')

scale = 1.0
rotation = config.getfloat('parameters', 'rotation')

max_timestep = config.getfloat('parameters', 'max_dt')
stop_sim_time = config.getfloat('parameters', 'T') + 0.1

# Bases
coords = d3.CartesianCoordinates('y', 'x')
dist = d3.Distributor(coords, dtype=dtype)
ybasis = d3.RealFourier(coords['y'], size=Ny, bounds=(-Ly/2, Ly/2), dealias=3/2)
xbasis = d3.ChebyshevT(coords['x'], size=Nx, bounds=(-Lx/2, Lx/2), dealias=3/2)
bases = (ybasis, xbasis)
ey, ex = coords.unit_vector_fields(dist)
y, x = ybasis.global_grid(), xbasis.global_grid()
y_g = y * np.ones_like(x)
x_g = x * np.ones_like(y)
dy = lambda A: d3.Differentiate(A, coords.coords[0])
dx = lambda A: d3.Differentiate(A, coords.coords[1])

# Fields
u = dist.VectorField(coords, name='u', bases=bases)
p = dist.Field(name='p', bases=bases)
tau_p = dist.Field(name='tau_p')
tau_u1 = dist.VectorField(coords, name='tau_u1', bases=(ybasis))
tau_u2 = dist.VectorField(coords, name='tau_u2', bases=(ybasis))

U = dist.VectorField(coords, name='U', bases=bases)
U['g'][1] = U0

# Mask function (airfoil geometry)
#################################################################
domain = domain.Domain(dist, bases)
slices = dist.grid_layout.slices(domain, scales=1)
phi = dist.Field(name='phi', bases=bases)
if True:

    a0 = -2.0
    a = [a0, 1.0, 0, 0]

    rot_exp = np.exp(1j*(rotation / 180 * np.pi))
    a = [ak*scale*rot_exp for ak in a]

    phi_g, rs = construct_phi(a, delta, dist, coords, bases)
    phi['g'] = phi_g
    dist.comm.Barrier()
    phi.change_scales(1)
    phi_g_global = phi.allgather_data('g')
