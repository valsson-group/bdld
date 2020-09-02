#!/usr/bin/env python3
import argparse
from typing import List, Optional, Union, Tuple

import numpy as np
import matplotlib.pyplot as plt
from bdld.helpers.plumed_header import PlumedHeader as PlmdHeader

from bdld.potential import Potential


def main() -> None:
    args = parse_cliargs()
    kt = args.kt
    bw = args.bw
    grid_spacing = args.grid_spacing
    if grid_spacing is None:
        if 0.5 * bw < 0.02:  # at least 20 points for gaussian
            grid_spacing = 0.5 * bw
        else:
            grid_spacing = 0.02
    convolution_file = args.convolution_file
    conv_image = args.conv_image
    log_conv_image = args.log_conv_image
    show_image = args.show_image

    # need to do some math to get the desired range after convolution
    wanted_max_of_conv = 2.5  # on both sides
    gauss_max = 5 * bw
    prob_max = wanted_max_of_conv + gauss_max
    grid_prob = np.arange(-prob_max, prob_max + grid_spacing, grid_spacing)
    grid_gauss = np.arange(-gauss_max, gauss_max + grid_spacing, grid_spacing)

    prob = get_prob(grid_prob, kt)
    gauss = gaussian(grid_gauss, 0, bw)
    conv = np.convolve(prob, gauss, mode="valid") * grid_spacing
    # valid conv range is shorter by len(gauss) - 1
    cutoff_conv = (len(prob) - len(conv)) // 2
    grid_conv = grid_prob[cutoff_conv:-cutoff_conv] if cutoff_conv != 0 else grid_prob
    if show_image or conv_image:
        plot_data = [
            ("K(x)", grid_gauss, gauss),
            ("π(x)", grid_prob, prob),
            ("K*π(x)", grid_conv, conv),
        ]
        plot_multiple(plot_data, f"bw {bw}", conv_image)

    # also throw away outer of prob and calculate the log
    prob = prob[cutoff_conv:-cutoff_conv] if cutoff_conv != 0 else prob
    log_conv = np.log(conv / prob)
    if show_image or log_conv_image:
        plot_data = [
            ("log(π)", grid_conv, np.log(prob)),
            ("log(K*π)", grid_conv, np.log(conv)),
        ]
        plot_multiple(plot_data, f"bw {bw}", log_conv_image)
    if show_image:
        plot_multiple([("log(K*π/π)", grid_conv, log_conv)])
    if convolution_file is not None:
        header = PlmdHeader(
            [
                "FIELDS pos, log(K*π/π), K*π",
                f"SET kt {kt}",
                f"SET bw {bw}",
            ]
        )
        np.savetxt(
            args.convolution_file,
            np.vstack((grid_conv, log_conv, conv)),
            fmt="%14.9f",
            header=str(header),
            comments="",
            delimiter=" ",
            newline="\n",
        )


def parse_cliargs() -> argparse.Namespace:
    """Use argparse to get cli arguments
    :return: args: Namespace with cli arguments"""

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-kT",
        "--temp",
        type=float,
        dest="kt",
        help="Energy (in units of kT) of the FES file",
        required=True,
    )
    parser.add_argument(
        "-bw",
        "--kernel-bandwidth",
        type=float,
        dest="bw",
        help="Bandwidth for gaussian kernels",
        required=True,
    )
    parser.add_argument(
        "--grid-spacing",
        type=float,
        dest="grid_spacing",
        help="Spacing of the grids used for evaluation. \
        By default it is 0.02 except but at most half the kernel bandwidth",
    )
    parser.add_argument(
        "-o",
        "--convolution-file",
        type=str,
        dest="convolution_file",
        help="Path to store the log of the convolution to",
    )
    parser.add_argument(
        "--conv-image",
        type=str,
        dest="conv_image",
        help="Name for the plot of the conv image",
    )
    parser.add_argument(
        "--log-conv-image",
        type=str,
        dest="log_conv_image",
        help="Name for the plot of the log_conv image",
    )
    parser.add_argument(
        "--show-image",
        action="store_true",
        dest="show_image",
        help="Also show some images directly.",
    )
    return parser.parse_args()


def gaussian(x: Union[float, np.ndarray], mu: float, sigma: float) -> float:
    """Standard normal distribution"""
    return (
        1 / (np.sqrt(2 * np.pi) * sigma) * np.exp(-((x - mu) ** 2) / (2 * sigma ** 2))
    )


def get_prob(grid: np.ndarray, kt: float) -> np.ndarray:
    """Get probability of double well potential"""
    pot = Potential(np.array([0, 0.0, -4, 0, 1]))
    prob = np.exp(-pot.calculate_reference(grid) / kt)
    # normalize although that doesn't matter for what is done here
    prob /= np.sum(prob) * (grid[1] - grid[0])
    return prob


def plot_multiple(
    data: List[Tuple[str, np.ndarray, np.ndarray]],
    title: Optional[str] = None,
    filename: Optional[str] = None,
) -> None:
    """Plot multiple data sets in a line figure

    :param data: The datasets as tuples (label, grid, values)
    :param filename: Optional filename to save the image
    """
    fig = plt.figure(figsize=(8, 4), dpi=100)
    ax = plt.axes()
    for d in data:
        ax.plot(d[1], d[2], label=d[0])
    ax.legend(title=title)
    if filename is not None:
        fig.savefig(filename)
    else:
        plt.show()


if __name__ == "__main__":
    main()
