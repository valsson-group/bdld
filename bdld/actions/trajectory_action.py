"""Module holding the TrajectoryAction class"""

from typing import List, Optional

import numpy as np

from bdld.actions.action import Action, get_valid_data
from bdld.actions.bussi_parinello_ld import BussiParinelloLD
from bdld.helpers.misc import initialize_file


class TrajectoryAction(Action):
    """Class that stories trajectories and writes them to file

    The write_stride parameter determines how many trajectory
    points are being held in memory even if they are never written.
    This allow other actions to use them.

    :param traj: fixed size numpy array holding the time and positions
                 it is written row-wise (i.e. every row represents a time)
                 and overwritten after being saved to file
    """

    def __init__(
        self,
        ld: BussiParinelloLD,
        stride: Optional[int] = None,
        filename: Optional[str] = None,
        write_stride: Optional[int] = None,
        write_fmt: Optional[str] = None,
    ) -> None:
        """Set up trajectory storage action

        :param ld: Langevin Dynamics to track
        :param stride: write every nth time step to file, default 1
        :param filename: base of filename(s) to write to
        :param write_stride: write to file every n time steps, default 100
        :param write_fmt: numeric format for saving the data, default "%14.9f"
        """
        print("Setting up storage of the trajectories")
        n_particles = len(ld.particles)
        self.ld = ld
        self.filenames: Optional[List[str]] = None
        self.stride: int = stride or 1
        self.write_stride: int = write_stride or 100
        # two data members for storing positions and time
        self.traj = np.empty((self.write_stride, n_particles, ld.pot.n_dim))
        self.times = np.empty((self.write_stride, 1))
        self.last_write: int = 0
        # write headers
        if filename:
            self.filenames = [f"{filename}.{i}" for i in range(n_particles)]
            self.write_fmt = write_fmt or "%14.9f"
            fields = ld.pot.get_fields()
            for i, fname in enumerate(self.filenames):
                ifields = [f"{f}.{i}" for f in fields]
                initialize_file(fname, ifields)
            print(f"Saving every {self.stride} point to the files '{filename}.{{i}}'")
        print()

    def run(self, step: int) -> None:
        """Store positions in traj array and write to file if write_stride is matched

        The stride parameters is ignored here and all times are temporarily stored
        This is because a HistogramAction using the data might have a different stride

        :param step: current simulation step
        """
        row = (step % self.write_stride) - 1  # saving starts at step 1
        self.times[row] = step * self.ld.dt
        self.traj[row] = [p.pos for p in self.ld.particles]

        if step % self.write_stride == 0:
            self.write(step)

    def final_run(self, step: int) -> None:
        """Write rest of trajectories to files"""
        self.write(step)

    def write(self, step: int) -> None:
        """Write currently stored trajectory data to file

        This can also be called between regular saves (e.g. at the end of the simulation)
        and will not result in missing or duplicate data
        Because the trajectories are stored in the array independently from the writes
        the function needs to do some arithmetics to find out what to write

        If no filenames were set this function will do nothing but not raise an exception

        :param step: current simulation step
        """
        if self.filenames:
            save_traj = get_valid_data(self.traj, step, self.stride, 1, self.last_write)
            save_times = get_valid_data(
                self.times, step, self.stride, 1, self.last_write
            )
            for i, filename in enumerate(self.filenames):
                with open(filename, "ab") as f:
                    np.savetxt(
                        f,
                        # 3d (times, walkers, pot_dims) to 2d array (times, pot_dims)
                        np.c_[save_times, save_traj[:, i]],
                        delimiter=" ",
                        newline="\n",
                        fmt=self.write_fmt,
                    )
                self.last_write = step
