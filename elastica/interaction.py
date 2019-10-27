__doc__ = """ Interaction module """

import numpy as np

from ._linalg import _batch_matmul, _batch_matvec, _batch_cross


# interpolator for slip velocity for kinetic friction
def linear_interpolation_slip(velocity_slip, velocity_threshold):
    abs_velocity_slip = np.fabs(velocity_slip)
    # velocity_threshold_array = velocity_threshold * np.array((3, velocity_slip.shape[1]))
    slip_function = np.ones((1, velocity_slip.shape[1]))
    slip_points = np.where(np.fabs(abs_velocity_slip) > velocity_threshold)
    slip_function[0, slip_points] = np.fabs(1.0
                                            - np.minimum(1.0, abs_velocity_slip /
                                                         velocity_threshold - 1.0))
    return slip_function


# base class for interaction
# only applies normal force no firctoon
class InteractionPlane:
    def __init__(self, k, nu, origin_plane, normal_plane):
        self.k = k
        self.nu = nu
        self.origin_plane = origin_plane
        self.normal_plane = normal_plane
        self.surface_tol = 1e-4

    def apply_normal_force(self, rod):
        element_x = 0.5 * (rod.position[..., :-1] + rod.position[..., 1:])
        distance_from_plane = self.normal_plane @ (element_x - self.origin_plane)
        no_contact_pts = np.where(distance_from_plane > self.surface_tol)
        nodal_total_forces = rod.internal_forces + rod.external_forces
        total_forces = 0.5 * (nodal_total_forces[..., :-1] + nodal_total_forces[..., 1:])
        forces_normal_direction = self.normal_plane @ total_forces
        forces_normal = np.outer(self.normal_plane, forces_normal_direction)
        forces_normal[..., np.where(forces_normal_direction > 0)] = 0
        plane_penetration = (np.minimum(distance_from_plane
                             - rod.r, 0.0))
        elastic_force = -self.k * np.outer(self.normal_plane,
                                           plane_penetration)
        element_v = 0.5 * (rod.velocity[..., :-1] + rod.velocity[..., 1:])
        normal_v = self.normal_plane @ element_v
        damping_force = -self.nu * np.outer(self.normal_plane, normal_v)
        normal_force_plane = -forces_normal
        normal_force_plane[..., no_contact_pts[1]] = 0
        total_force_plane = normal_force_plane + elastic_force + damping_force
        rod.external_forces[..., :-1] += 0.5 * total_force_plane
        rod.external_forces[..., 1:] += 0.5 * total_force_plane
        return normal_force_plane


# class for anisotropic frictional plane
# NOTE: friction coefficients are passed as arrays in the order
# mu_forward : mu_backward : mu_sideways
# head is at x[0] and forward means head to tail
class AnistropicFrictionalPlane(InteractionPlane):
    def __init__(self, k, nu, origin_plane, normal_plane, slip_velocity_tol,
                 static_mu_array, kinetic_mu_array):
        InteractionPlane.__init__(self, k, nu, origin_plane, normal_plane)
        self.slip_velocity_tol = slip_velocity_tol
        self.static_mu_forward = static_mu_array[0]
        self.static_mu_backward = static_mu_array[1]
        self.static_mu_sideways = static_mu_array[2]
        self.kinetic_mu_forward = kinetic_mu_array[0]
        self.kinetic_mu_backward = kinetic_mu_array[1]
        self.kinetic_mu_sideways = kinetic_mu_array[2]

# kinetic and static friction are separate functions
    def apply_kinetic_friction(self, rod):
        # calculate axial and rolling directions
        normal_force_plane = self.apply_normal_force(self, rod)
        normal_plane_array = np.outer(self.normal_plane, np.ones((1,
                                      normal_force_plane.shape[1])))
        axial_direction = rod.tangents
        element_v = 0.5 * (rod.velocity[..., :-1] + rod.velocity[..., 1:])
        # first apply axial kinetic friction
        # dot product
        axial_slip_velocity = np.sqrt(np.einsum('ijk,ijk->jk', element_v, axial_direction))
        axial_slip_velocity_sign = np.sign(axial_slip_velocity)
        kinetic_mu = 0.5 * (self.kinetic_mu_forward * (1 - axial_slip_velocity_sign)
                            + self.kinetic_mu_backward * (1 + axial_slip_velocity_sign))
        slip_function = (axial_slip_velocity, self.slip_velocity_tol)
        axial_kinetic_friction_force = -((1.0 - slip_function) * kinetic_mu *
                                         normal_force_plane * axial_slip_velocity_sign
                                         * axial_direction)
        rod.external_forces[..., :-1] += 0.5 * axial_kinetic_friction_force
        rod.external_forces[..., 1:] += 0.5 * axial_kinetic_friction_force

        # now rolling kinetic friction
        rolling_direction = _batch_cross(normal_plane_array, axial_direction)
