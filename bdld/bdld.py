#!/usr/bin/env python3

import numpy as np
from birth_death import BirthDeath
import analysis
from histogram import Histogram
from helpers.plumed_header import PlumedHeader as PlmdHeader


class BirthDeathLangevinDynamics():
    """Combine Langevin dynamics with birth/death events

    :param ld: completely set up BussiParinelloLD instance
    :type ld: bussi_parinello_ld.BussiParinelloLD
    :param bd: BirthDeath instance that will be generated by the setup() function
    :type bd: birth_death.BirthDeath
    :param bd_stride: number of ld steps between execution of the birth/death algorithm, defaults to 0 (no bd)
    :type bd_stride: int, optional
    :param bd_time_step: time between bd events in units of the ld
    :type bd_time_step: float
    :param bd_seed: seed for the RNG of the birth/death algorithm
    :type bd_seed: int, optional
    :param bd_bw: bandwidth for gaussian kernels per direction used in birth/death
    :type bd_bw: float, optional if bd_stride is 0
    :param traj: trajectories of all particles
    :type traj: list containing one list per particle
    :param steps_since_bd: counts the passed steps since the last execution of the birth/death algorithm
    :type steps_since_bd: int
    """

    def __init__(self, ld, bd_stride=0, bd_bw=0, bd_seed=None):
        """Generate needed varables and the birth/death instance from arguments"""
        self.ld = ld
        self.bd = None
        self.bd_stride = bd_stride
        self.bd_time_step = ld.dt * bd_stride
        self.bd_seed = bd_seed
        self.bd_bw = bd_bw
        self.traj = []
        self.steps_since_bd = 0
        self.histo = None
        self.histo_stride = 0
        self.setup()

    def setup(self):
        """Set up bd and initialize trajectory lists"""
        if self.bd_stride != 0:
            if any(bw <= 0 for bw in self.bd_bw):
                raise ValueError(f"The bandwidth of the Gaussian kernels needs"
                                 f"to be greater than 0 (is {self.bd_bw})")
            self.setup_bd()
        # initialize trajectory list
        self.traj = [[np.copy(p.pos)] for p in self.ld.particles]

    def setup_bd(self):
        """Set up birth death from parameters"""
        if self.bd_stride != 0:
            self.bd = BirthDeath(self.ld.particles,
                                 self.bd_time_step,
                                 self.bd_bw,
                                 self.ld.kt,
                                 self.bd_seed,
                                 True,
                                 )

    def init_histogram(self, n_bins, ranges, stride=None):
        """Initialize a histogram for the trajectories

        :param n_bins: number of bins of the histogram per dimension
        :type n_bins: list or numpy array
        :param ranges: extent of histogram (min, max) per dimension
        :type ranges: list of tuples
        :param int stride: add trajectory to the histogram every n steps
        """
        if self.ld.pot.n_dim != len(n_bins):
            e = "Dimensions of histogram bins don't match dimensions of system " \
                + f"({len(n_bins)} vs. {self.ld.n_dim})"
            raise ValueError(e)
        if self.ld.pot.n_dim != len(ranges):
            e = "Dimensions of histogram ranges don't match dimensions of system " \
                + f"({len(ranges)} vs. {self.ld.n_dim})"
            raise ValueError(e)
        self.histo = Histogram(n_bins, ranges)
        self.histo_stride = stride
        if self.histo_stride is None:
            # add to histogram every 1,000,000 trajectory points by default
            self.histo_stride = 1000000 / len(self.ld.particles)

    def add_trajectory_to_histogram(self, clear_traj):
        """Add trajectory data to histogram

        :param bool clear_traj: delete the trajectory data after adding to histogram
        """
        comb_traj = np.vstack([pos for part in self.traj for pos in part])
        self.histo.add(comb_traj)
        if clear_traj:
            self.traj = [ [] for i in range(len(self.ld.particles))]

    def run(self, num_steps):
        """Run the simulation for given number of steps

        It performs first the Langevin dynamics, then optionally the birth/death
        steps and then saves the positions of the particles to the trajectories.

        The num_steps argument takes the previous steps into account for the
        birth/death stride. For example having a bd_stride of 10 and first
        running for 6 and then 7 steps will perform a birth/death step on the
        4th step of the second run.

        :param int num_steps: Number of steps to run
        """
        for i in range(self.steps_since_bd + 1, self.steps_since_bd + 1 + num_steps):
            self.ld.step()
            if (self.bd_stride != 0 and i % self.bd_stride == 0):
                self.bd.step()
            for j,p in enumerate(self.ld.particles):
                self.traj[j].append(np.copy(p.pos))
            if (self.histo_stride != 0 and i % self.histo_stride == 0):
                self.add_trajectory_to_histogram(True)
        # increase counter only once
        if self.bd_stride != 0:
            self.steps_since_bd = (self.steps_since_bd + num_steps) % self.bd_stride

    def save_analysis_grid(self, filename, grid):
        """Analyse the values of rho and beta on a grid

        :param filename: path to save grid to
        :param grid: list or numpy array with positions to calculate values
        """
        ana_ene = [self.ld.pot.evaluate(p)[0] for p in grid]
        ana_values = self.bd.prob_density_grid(grid, ana_ene)
        header = self.generate_fileheader(['pos', 'rho', 'beta'])
        np.savetxt(filename, ana_values, fmt='%14.9f', header=str(header),
                   comments='', delimiter=' ', newline='\n')

    def save_trajectories(self, filename):
        """Save all trajectories to files

        :param filename: basename for files, is appended by '.i' for the individual files
        """
        for i,t in enumerate(self.traj):
            header = self.generate_fileheader([f'traj.{i}'])
            np.savetxt(filename + '.' + str(i), t, header=str(header),
                       comments='', delimiter=' ', newline='\n')

    def save_fes(self, filename):
        """Calculate FES and save to text file

        This does histogramming of the trajectories first if necessary

        :param string filename: path to save FES to
        """
        if any(t for t in self.traj):
            self.add_trajectory_to_histogram(True)
        fes, pos = self.histo.calculate_fes(self.ld.kt)
        header = self.generate_fileheader(['pos fes'])
        data = np.vstack((pos, fes)).T
        np.savetxt(filename, data, header=str(header),
                   comments='', delimiter=' ', newline='\n')

    def plot_fes(self, filename=None, plot_domain=None, plot_title=None):
        """Plot fes with reference and optionally save to file

        :param filename: optional filename to save figure to
        :param plot_domain: optional list with minimum and maximum value to show
        :param plot_title: optional title for the legend
        """
        if any(t for t in self.traj):
            self.add_trajectory_to_histogram(True)
        if self.histo.fes is None:
            self.histo.calculate_fes(self.ld.kt)
        analysis.plot_fes(self.histo.fes, self.histo.bin_centers(),
                          # temporary fix, needs to be changed for more than 1d
                          ref=self.ld.pot.calculate_reference(self.histo.bin_centers()[0]),
                          plot_domain=plot_domain, filename=filename, title=plot_title)


    def generate_fileheader(self, fields):
        """Get plumed-style header from variables to print with data to file

        :param fields: list of strings for the field names (first line of header)
        :return header:
        """
        header = PlmdHeader([' '.join(['FIELDS'] + fields),
                             f'SET dt {self.ld.dt}',
                             f'SET kt {self.ld.kt}',
                             f'SET friction {self.ld.friction}',
                             f'SET bd_stride {self.bd_stride}',
                             f'SET bd_bandwidth {self.bd_bw}',
                             ])
        return header
