import numpy as np
import matplotlib.pyplot as plt
import dedalus.public as d3
from dedalus.core import domain
import logging
logger = logging.getLogger(__name__)
from scipy.optimize import minimize

# Parameters
Lx, Ly = 10, 2*np.pi
Nx, Ny = 256, 128
dtype = np.float64
Reynolds = 1e2
nu = 1 / Reynolds
U0 = 1
tau = 5e0
max_timestep = 0.001
stop_sim_time = 1e-1

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
if False:
    from construct_phi import construct_phi
    phi_g = construct_phi(dist, coords, bases)
    with open('phi_g.npy', 'wb') as f:
        np.save(f, phi_g)
else:
    with open('phi_g.npy', 'rb') as f:
        phi_g = np.load(f)

# phi_g = np.exp(-(r / sigma)**2)
domain = domain.Domain(dist, bases)
slices = dist.grid_layout.slices(domain, scales=1)
phi = dist.Field(name='phi', bases=bases)
phi['g'] = phi_g[slices]
logger.info('done solving SDF. Mask function phi constructed.')

#################################################################


lift_basis = xbasis.derivative_basis(1) # First derivative basis
lift = lambda A, n: d3.Lift(A, lift_basis, n)
grad_u = d3.grad(u) + ex*lift(tau_u1,-1) # First-order reduction

problem = d3.IVP([u, p, tau_p, tau_u1, tau_u2], namespace=locals())

problem.add_equation("trace(grad_u) + tau_p = 0")
# problem.add_equation("dt(u) + grad(p) - nu*div(grad_u) + lift(tau_u2, -1) =  ")
problem.add_equation("dt(u) + grad(p) - nu*div(grad_u) + lift(tau_u2, -1) = -u@grad(u) - phi*(u)/tau")

if False:
    problem.add_equation("u(x='left') = u(x='right')")
    problem.add_equation("dx(u)(x='left') = dx(u)(x='right')")
else:
    # problem.add_equation("u(x='left') = 0")
    # problem.add_equation("u(x='right') = 0")

    problem.add_equation("(u @ ex)(x='left') = U0")
    problem.add_equation("(u @ ey)(x='left') = 0")

    problem.add_equation("(u @ ex)(x='right') = U0")
    problem.add_equation("(u @ ey)(x='right') = 0")

problem.add_equation("integ(p) = 0") # Pressure gauge

u['g'] = U['g'].copy()

# Solver
solver = problem.build_solver(d3.RK222)
solver.stop_sim_time = stop_sim_time

CFL = d3.CFL(solver, initial_dt=max_timestep, cadence=10, safety=0.5, threshold=0.1,
             max_change=1.5, min_change=0.5, max_dt=max_timestep)
CFL.add_velocity(u)

# Flow properties
flow = d3.GlobalFlowProperty(solver, cadence=10)
flow.add_property(np.sqrt((u@ex)**2 + (u@ey)**2), name='u_mag')

ts = []
max_us = []

while solver.proceed:
    timestep = CFL.compute_timestep()
    solver.step(timestep)
    if (solver.iteration-1) % 10 == 0:
        max_u_mag = flow.max('u_mag')
        max_us.append(max_u_mag)
        ts.append(solver.sim_time)
        logger.info('Iteration=%i, Time=%e, dt=%e, max(|u|)=%f' %(solver.iteration, solver.sim_time, timestep, max_u_mag))

if (dist.comm.rank == 0):
    plt.plot(ts, max_us)
    plt.xlabel(r"$t$")
    plt.ylabel(r"$L-\infty [\vec{u}]$")
    plt.show()
dist.comm.Barrier()

# Gather global data
x = xbasis.global_grid()
y = ybasis.global_grid()
# u.change_scales(1)
ux = ((u) @ ex).evaluate()
ux.change_scales(1)
ugx = ux.allgather_data('g')

uy = ((u) @ ey).evaluate()
uy.change_scales(1)
ugy = uy.allgather_data('g')
mag_u = np.sqrt(ugx**2 + ugy**2)

# Plot
if dist.comm.rank == 0:
    plt.figure(figsize=(6, 4))
    res = 8
    # plt.pcolormesh(x.ravel(), y.ravel(), phi_g.T, cmap='viridis', shading='gouraud', rasterized=True)
    plt.pcolormesh(x.ravel(), y.ravel(), ugx, cmap='seismic', shading='gouraud', rasterized=True)
    plt.quiver(x_g.T[::res, ::res], y_g.T[::res, ::res], ugx.T[::res, ::res], ugy.T[::res, ::res])
    plt.gca().set_aspect('equal')
    plt.xlabel('x')
    plt.ylabel('y')
    # plt.title("Flow Speed")
    plt.tight_layout()
    # plt.savefig('stokes.pdf')
    plt.savefig('ns_flow.png', dpi=200)
    # plt.show()