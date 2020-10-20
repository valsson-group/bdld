"""Main bdld algorithm file hosting the BirthDeathLangevinDynamics class"""

from typing import List, Optional, Tuple, Union
import numpy as np

from bdld.helpers.plumed_header import PlumedHeader as PlmdHeader

from bdld import analysis
from bdld.birth_death import BirthDeath
from bdld.bussi_parinello_ld import BussiParinelloLD
from bdld.histogram import Histogram
from bdld.grid import Grid


class BirthDeathLangevinDynamics:
    """Combine Langevin dynamics with birth/death events

    :param ld: completely set up BussiParinelloLD instance
    :param bd: BirthDeath instance that will be generated by the setup() function
    :param bd_stride: number of ld steps between execution of the birth/death algorithm, defaults to 0 (no bd)
    :param bd_time_step: time between bd events in units of the ld
    :param bd_seed: seed for the RNG of the birth/death algorithm
    :param bd_bw: bandwidth for gaussian kernels per direction used in birth/death
    :param traj: trajectories of all particles
    :param traj_filenames: filenames to save trajectories to
    :param total_steps: counts the total passed steps
    :param histo: optional histogram to bin the trajectory values
    :param histo_stride: stride between binning to the histogram
    :param kde: use KDE from statsmodels to estimate walker density
    """

    def __init__(
        self,
        ld: BussiParinelloLD,
        bd_stride: int = 0,
        bd_bw: List[float] = [0.0],
        bd_seed: Optional[int] = None,
        kde: bool = False,
    ) -> None:
        """Generate needed varables and the birth/death instance from arguments"""
        self.ld: BussiParinelloLD = ld
        self.bd: Optional[BirthDeath] = None
        self.bd_stride: int = bd_stride
        self.bd_time_step: float = ld.dt * bd_stride
        self.bd_seed: Optional[int] = bd_seed
        self.bd_bw: List[float] = bd_bw
        self.traj: List[List[np.ndarray]] = []
        self.traj_filenames: List[str] = []
        self.total_steps: int = 0
        self.histo: Optional[Histogram] = None
        self.histo_stride: int = 0
        self.kde: bool = kde
        self.setup()

    def setup(self) -> None:
        """Perform parameter checks, set up bd and initialize trajectory lists"""
        if self.bd_stride != 0:
            if self.ld.pot.n_dim != len(self.bd_bw):
                raise ValueError(
                    "Dimensions of potential and birth/death kernel bandwidths do not match"
                    f"({self.ld.pot.n_dim} vs {len(self.bd_bw)}"
                )
            if any(bw <= 0 for bw in self.bd_bw):
                raise ValueError(
                    f"The bandwidth of the Gaussian kernels needs"
                    f"to be greater than 0 (is {self.bd_bw})"
                )
            self.setup_bd()
        # initialize trajectory list
        self.traj = [[np.copy(p.pos)] for p in self.ld.particles]

    def setup_bd(self) -> None:
        """Set up BirthDeath from parameters"""
        if self.bd_stride != 0:
            prob_density = self.bd_prob_density()
            self.bd = BirthDeath(
                self.ld.particles,
                self.bd_time_step,
                self.bd_bw,
                self.ld.kt,
                prob_density,
                self.bd_seed,
                True,
                self.kde,
            )

    def bd_prob_density(self) -> Grid:
        """Return probability density grid needed for BirthDeath

        This is somewhat hacky at the moment:
        To avoid edge effects in the convolution the grid area is chosen such that
        cutting off after convolution yields exactly the potential range, so a larger
        than the intrinsic range of the potential is used which usually couldn't be done

        Also this is usually a unknown quantity, so this has to be replaced by an estimate
        in the future. E.g. enforce usage of the histogram and use that as estimate at
        current time with iterative updates

        :return grid: Grid of the density points
        :return prob: Probability values
        """
        ranges = []
        grid_points = []
        for dim in range(self.ld.pot.n_dim): # this is usually not possible
            grid_min, grid_max = self.ld.pot.ranges[dim]
            grid_min -= 5 * self.bd_bw[dim]  # enlarge by area affected by edge effects
            grid_max += 5 * self.bd_bw[dim]
            ranges.append((grid_min, grid_max))
            # have at least 20 points of gaussian within 5 sigma
            min_points_gaussian = int(np.ceil((grid_max - grid_min) / (0.5 * self.bd_bw[dim])))
            grid_points.append(max(1001, min_points_gaussian))
        return self.ld.pot.calculate_probability_density(self.ld.kt, ranges, grid_points)

    def init_histo(
        self, n_bins: List[int], ranges: List[Tuple[float, float]], stride=None
    ) -> None:
        """Initialize a histogram for the trajectories

        :param n_bins: number of bins of the histogram per dimension
        :param ranges: extent of histogram (min, max) per dimension
        :param int stride: add trajectory to the histogram every n steps
        """
        if self.ld.pot.n_dim != len(n_bins):
            e = (
                "Dimensions of histogram bins don't match dimensions of system "
                + f"({len(n_bins)} vs. {self.ld.pot.n_dim})"
            )
            raise ValueError(e)
        if self.ld.pot.n_dim != len(ranges):
            e = (
                "Dimensions of histogram ranges don't match dimensions of system "
                + f"({len(ranges)} vs. {self.ld.pot.n_dim})"
            )
            raise ValueError(e)
        self.histo = Histogram(n_bins, ranges)
        self.histo_stride = stride
        if self.histo_stride is None:
            # add to histogram every 1,000,000 trajectory points by default
            self.histo_stride = 1000000 // len(self.ld.particles)

    def init_traj_files(self, filenames: List[str]) -> None:
        """Initialize files to save trajectories to

        This writes the headers to the specified files so they
        can be filled by the 'save_trajectories()' function

        :param filenames: list filenames per particle
        """
        if len(filenames) != len(self.ld.particles):
            raise ValueError(
                "Number of trajectory files does not match number of particles"
            )
        for i, name in enumerate(filenames):
            header = self.generate_fileheader([f"traj.{i}"])
            with open(name, "w") as f:
                f.write(str(header))
        self.traj_filenames = filenames

    def add_traj_to_histo(self) -> None:
        """Add trajectory data to histogram

        :param bool clear_traj: delete the trajectory data after adding to histogram
        """
        if not self.histo:
            raise ValueError("Histogram was not initialized yet")
        comb_traj = np.vstack([pos for part in self.traj for pos in part])
        self.histo.add(comb_traj)
        self.save_traj(clear=True)

    def run(self, num_steps: int) -> None:
        """Run the simulation for given number of steps

        It performs first the Langevin dynamics, then optionally the birth/death
        steps and then saves the positions of the particles to the trajectories.

        The num_steps argument takes the previous steps into account for the
        birth/death stride. For example, having a bd_stride of 10 and first
        running for 6 and then 7 steps will perform a birth/death step on the
        4th step of the second run.

        :param int num_steps: Number of steps to run
        """
        for i in range(self.total_steps + 1, self.total_steps + 1 + num_steps):
            self.ld.step()
            if self.bd and i % self.bd_stride == 0:
                self.bd.step()
            for j, p in enumerate(self.ld.particles):
                self.traj[j].append(np.copy(p.pos))
            if self.histo and i % self.histo_stride == 0:
                self.add_traj_to_histo()
        self.total_steps += num_steps

    def save_analysis_grid(
        self, filename: str, grid: Union[List[np.ndarray], np.ndarray]
    ) -> None:
        """Analyse the values of rho and beta on a grid

        :param filename: path to save grid to
        :param grid: list or numpy array with positions to calculate values
        """
        if not self.bd:
            raise ValueError("No birth/death to analize")
        ana_ene = [self.ld.pot.energy(p) for p in grid]
        ana_values = self.bd.walker_density_grid(grid, ana_ene)
        header = self.generate_fileheader(["pos", "rho", "beta"])
        np.savetxt(
            filename,
            ana_values,
            fmt="%14.9f",
            header=str(header),
            comments="",
            delimiter=" ",
            newline="\n",
        )

    def save_traj(self, clear: bool) -> None:
        """Save all trajectories to files (append)

        This also empties the traj held in memory.
        Files need to be initialized with init_traj_files() before
        """
        # loops over nothing if no files initialized
        for i, name in enumerate(self.traj_filenames):
            with open(name, "ab") as f:
                np.savetxt(f, self.traj[i], delimiter=" ", newline="\n")
        if clear:
            self.traj = [[] for i in range(len(self.ld.particles))]

    def save_fes(self, filename: str) -> None:
        """Calculate FES and save to text file

        This does histogramming of the trajectories first if necessary

        :param string filename: path to save FES to
        """
        if not self.histo:
            raise ValueError("Histogram for FES needs to be initialized first")
        if any(t for t in self.traj):
            self.add_traj_to_histo()
        fes, pos = self.histo.calculate_fes(self.ld.kt)
        header = self.generate_fileheader(["pos fes"])
        data = np.vstack((pos, fes)).T
        np.savetxt(
            filename, data, header=str(header), comments="", delimiter=" ", newline="\n"
        )

    def plot_fes(
        self,
        filename: Optional[str] = None,
        plot_domain: Optional[Tuple[float, float]] = None,
        plot_title: Optional[str] = None,
    ) -> None:
        """Plot fes with reference and optionally save to file

        :param filename: optional filename to save figure to
        :param plot_domain: optional list with minimum and maximum value to show
        :param plot_title: optional title for the legend
        """
        if not self.histo:
            raise ValueError("Histogram for FES needs to be initialized first")
        if any(t for t in self.traj):
            self.add_traj_to_histo()
        if self.histo.fes is None:
            self.histo.calculate_fes(self.ld.kt)
        analysis.plot_fes(
            self.histo.fes,
            self.histo.bin_centers(),
            # temporary fix, needs to be changed for more than 1d
            ref=self.ld.pot.calculate_reference(self.histo.bin_centers()[0]),
            plot_domain=plot_domain,
            filename=filename,
            title=plot_title,
        )

    def generate_fileheader(self, fields: List[str]) -> PlmdHeader:
        """Get plumed-style header from variables to print with data to file

        :param fields: list of strings for the field names (first line of header)
        :return header:
        """
        header = PlmdHeader(
            [
                " ".join(["FIELDS"] + fields),
                f"SET dt {self.ld.dt}",
                f"SET kt {self.ld.kt}",
                f"SET friction {self.ld.friction}",
            ]
        )
        if self.bd_stride != 0:
            header.append_lines(
                [
                    f"SET bd_stride {self.bd_stride}",
                    f"SET bd_bandwidth {self.bd_bw}",
                ]
            )
        return header
