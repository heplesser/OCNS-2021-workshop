import numpy as np
from scipy.signal import convolve
from sklearn.linear_model import LinearRegression
from tqdm import tqdm
import time


########################################################################################################
def convolve_spk(times, neurons, recorded_neurons, simtime, tau, resolution):
    tt_e = np.arange(0, 5*tau, resolution)
    kernel = np.exp(-tt_e/tau)

    num_steps = int(simtime/resolution)
    tt = np.arange(0, simtime, resolution)
    tt = np.linspace(0, simtime, num_steps-1)
    states = np.zeros((len(recorded_neurons), num_steps))

    nrns = np.full(np.max(recorded_neurons) + 1, -1, dtype=int)
    nrns[recorded_neurons] = [i for i in range(len(recorded_neurons))]

    ids = np.digitize(times, tt)
    states[nrns[neurons], ids] = 1

    smooth = [convolve(states[i], kernel) for i in range(len(recorded_neurons))]

    return np.array(smooth)[:, :num_steps]


def generate_input(num_steps, step_duration, resolution, scale):
    """
    Generates a piecewise constant input signal with amplitudes drawn from a uniform distribution

    Parameters
    ----------
    num_steps: int
        number of steps in the step function
    step_duration: int
        duration of each step in ms
    resolution: float
        resolution of the generated signal
    scale: float
        amplitude scaling parameter
    Returns
    -------
    ndarray
        continuous input signal (between -1 and 1)
    ndarray
        time vector with all the times for which the signal is generated
    ndarray
        times at which signal amplitude shifts
    ndarray
        amplitudes
    """
    dist_range = [-1., 1.]
    rand_distr = np.random.uniform(low=dist_range[0], high=dist_range[1], size=num_steps)
    rand_distr = rand_distr + abs(min(dist_range))
    inp_times = np.arange(resolution, num_steps * step_duration, step_duration)
    time_vec = np.arange(0, num_steps * step_duration + resolution, resolution)
    signal = np.zeros_like(time_vec)
    for tt in range(len(inp_times)):
        end_idx = int(round(inp_times[tt + 1] / resolution)) if tt + 1 < len(inp_times) else None
        signal[int(round(inp_times[tt] / resolution)):end_idx] = rand_distr[tt]

    return signal, time_vec, inp_times, rand_distr * scale


def compute_capacity(X, z):
    """
    Compute capacity to reconstruct z based on linearly combining x
    :param X: state matrix (NxT)
    :param z: target output (1xT)
    :return: capacity
    """
    t_start = time.time()
    #reg = Ridge(alpha=100000.0, fit_intercept=False).fit(X.T, z)

    reg = LinearRegression(n_jobs=-1, fit_intercept=False, copy_X=False).fit(X.T, z)
    z_hat = reg.predict(X.T)
    covs = (np.cov(z_hat, z)[0, 1] ** 2.)
    vars = (np.var(z) * np.var(z_hat))
    capacity = covs / vars
    error = np.mean((z - z_hat) ** 2)
    norm = np.linalg.norm(reg.coef_)
    # print("\nElapsed time: {} s".format(time.time() - t_start))

    return z_hat, capacity, error, reg.coef_


def ccf(x, y, axis=None):
    """
    Fast cross correlation function based on fft.

    Computes the cross-correlation function of two series.
    Note that the computations are performed on anomalies (deviations from
    average).
    Returns the values of the cross-correlation at different lags.
    """
    assert x.ndim == y.ndim, "Inconsistent shape !"
    if axis is None:
        if x.ndim > 1:
            x = x.ravel()
            y = y.ravel()
        npad = x.size + y.size
        xanom = (x - x.mean(axis=None))
        yanom = (y - y.mean(axis=None))
        Fx = np.fft.fft(xanom, npad, )
        Fy = np.fft.fft(yanom, npad, )
        iFxy = np.fft.ifft(Fx.conj() * Fy).real
        varxy = np.sqrt(np.inner(xanom, xanom) * np.inner(yanom, yanom))
    else:
        npad = x.shape[axis] + y.shape[axis]
        if axis == 1:
            if x.shape[0] != y.shape[0]:
                raise ValueError("Arrays should have the same length!")
            xanom = (x - x.mean(axis=1)[:, None])
            yanom = (y - y.mean(axis=1)[:, None])
            varxy = np.sqrt((xanom * xanom).sum(1) *
                            (yanom * yanom).sum(1))[:, None]
        else:
            if x.shape[1] != y.shape[1]:
                raise ValueError("Arrays should have the same width!")
            xanom = (x - x.mean(axis=0))
            yanom = (y - y.mean(axis=0))
            varxy = np.sqrt((xanom * xanom).sum(0) * (yanom * yanom).sum(0))
        Fx = np.fft.fft(xanom, npad, axis=axis)
        Fy = np.fft.fft(yanom, npad, axis=axis)
        iFxy = np.fft.ifft(Fx.conj() * Fy, n=npad, axis=axis).real
    # We just turn the lags into correct positions:
    iFxy = np.concatenate((iFxy[len(iFxy) // 2:len(iFxy)],
                           iFxy[0:len(iFxy) // 2]))
    return iFxy / varxy

# ##########################################################################################################
# Below we define some classes, to simplify the data analysis for the exercices. These have been adapted from NeuroTools
import re
from sys import exit

import numpy as np
from matplotlib import pyplot as pl
from scipy import signal as sp


class SpikeTrain(object):
    """
    SpikeTrain(spikes_times, t_start=None, t_stop=None)
    This class defines a spike train as a list of times events.

    Event times are given in a list (sparse representation) in milliseconds.

    Inputs:
        spike_times - a list/numpy array of spike times (in milliseconds)
        t_start     - beginning of the SpikeTrain (if not, this is inferred)
        t_stop      - end of the SpikeTrain (if not, this is inferred)

    Examples:
        >> s1 = SpikeTrain([0.0, 0.1, 0.2, 0.5])
        >> s1.isi()
            array([ 0.1,  0.1,  0.3])
        >> s1.mean_rate()
            8.0
        >> s1.cv_isi()
            0.565685424949
    """

    def __init__(self, spike_times, t_start=None, t_stop=None):
        """
        Constructor of the SpikeTrain object
        """

        self.t_start = t_start
        self.t_stop = t_stop
        self.spike_times = np.array(spike_times, np.float32)

        # If t_start is not None, we resize the spike_train keeping only
        # the spikes with t >= t_start
        if self.t_start is not None:
            self.spike_times = np.extract((self.spike_times >= self.t_start), self.spike_times)

        # If t_stop is not None, we resize the spike_train keeping only
        # the spikes with t <= t_stop
        if self.t_stop is not None:
            self.spike_times = np.extract((self.spike_times <= self.t_stop), self.spike_times)

        # We sort the spike_times. May be slower, but is necessary for quite a
        # lot of methods
        self.spike_times = np.sort(self.spike_times, kind="quicksort")
        # Here we deal with the t_start and t_stop values if the SpikeTrain
        # is empty, with only one element or several elements, if we
        # need to guess t_start and t_stop
        # no element : t_start = 0, t_stop = 0.1
        # 1 element  : t_start = time, t_stop = time + 0.1
        # several    : t_start = min(time), t_stop = max(time)

        size = len(self.spike_times)
        if size == 0:
            if self.t_start is None:
                self.t_start = 0
            if self.t_stop is None:
                self.t_stop = 0.1
        elif size == 1:  # spike list may be empty
            if self.t_start is None:
                self.t_start = self.spike_times[0]
            if self.t_stop is None:
                self.t_stop = self.spike_times[0] + 0.1
        elif size > 1:
            if self.t_start is None:
                self.t_start = np.min(self.spike_times)
            if np.any(self.spike_times < self.t_start):
                raise ValueError("Spike times must not be less than t_start")
            if self.t_stop is None:
                self.t_stop = np.max(self.spike_times)
            if np.any(self.spike_times > self.t_stop):
                raise ValueError("Spike times must not be greater than t_stop")

        if self.t_start >= self.t_stop :
            raise Exception("Incompatible time interval : t_start = %s, t_stop = %s" % (self.t_start, self.t_stop))
        if self.t_start < 0:
            raise ValueError("t_start must not be negative")
        if np.any(self.spike_times < 0):
            raise ValueError("Spike times must not be negative")

    def __str__(self):
        return str(self.spike_times)

    def __del__(self):
        del self.spike_times

    def __len__(self):
        return len(self.spike_times)

    def __getslice__(self, i, j):
        """
        Return a sub-list of the spike_times vector of the SpikeTrain, indexed by i,j
        """
        return self.spike_times[i:j]

    def time_parameters(self):
        """
        Return the time parameters of the SpikeTrain (t_start, t_stop)
        """
        return (self.t_start, self.t_stop)

    def is_equal(self, spktrain):
        """
        Return True if the SpikeTrain object is equal to one other SpikeTrain, i.e
        if they have same time parameters and same spikes_times

        Inputs:
            spktrain - A SpikeTrain object

        See also:
            time_parameters()
        """
        test = (self.time_parameters() == spktrain.time_parameters())
        return np.all(self.spike_times == spktrain.spike_times) and test

    def copy(self):
        """
        Return a copy of the SpikeTrain object
        """
        return SpikeTrain(self.spike_times, self.t_start, self.t_stop)

    def duration(self):
        """
        Return the duration of the SpikeTrain
        """
        return self.t_stop - self.t_start

    def merge(self, spiketrain, relative=False):
        """
        Add the spike times from a spiketrain to the current SpikeTrain

        Inputs:
            spiketrain - The SpikeTrain that should be added
            relative - if True, relative_times() is called on both spiketrains before merging

        Examples:
            >> a = SpikeTrain(range(0,100,10),0.1,0,100)
            >> b = SpikeTrain(range(400,500,10),0.1,400,500)
            >> a.merge(b)
            >> a.spike_times
                [   0.,   10.,   20.,   30.,   40.,   50.,   60.,   70.,   80.,
                90.,  400.,  410.,  420.,  430.,  440.,  450.,  460.,  470.,
                480.,  490.]
            >> a.t_stop
                500
        """
        if relative:
            self.relative_times()
            spiketrain.relative_times()
        self.spike_times = np.insert(self.spike_times, self.spike_times.searchsorted(spiketrain.spike_times), \
                                     spiketrain.spike_times)
        self.t_start = min(self.t_start, spiketrain.t_start)
        self.t_stop = max(self.t_stop, spiketrain.t_stop)

    def format(self, relative=False, quantized=False):
        """
        Return an array with a new representation of the spike times

        Inputs:
            relative  - if True, spike times are expressed in a relative
                       time compared to the previous one
            quantized - a value to divide spike times with before rounding

        Examples:
            >> st.spikes_times=[0, 2.1, 3.1, 4.4]
            >> st.format(relative=True)
                [0, 2.1, 1, 1.3]
            >> st.format(quantized=2)
                [0, 1, 2, 2]
        """
        spike_times = self.spike_times.copy()

        if relative and len(spike_times) > 0:
            spike_times[1:] = spike_times[1:] - spike_times[:-1]

        if quantized:
            assert quantized > 0, "quantized must either be False or a positive number"
            spike_times = (spike_times/quantized).round().astype('int')

        return spike_times

    def jitter(self, jitter):
        """
        Returns a new SpikeTrain with spiketimes jittered by a normal distribution.

        Inputs:
              jitter - sigma of the normal distribution

        Examples:
              >> st_jittered = st.jitter(2.0)
        """

        return SpikeTrain(self.spike_times+jitter*(np.random.normal(loc=0.0, scale=1.0, size=self.spike_times.shape[
            0])), t_start=self.t_start, t_stop=self.t_stop)

    #######################################################################
    # Analysis methods that can be applied to a SpikeTrain object         #
    #######################################################################
    def isi(self):
        """
        Return an array with the inter-spike intervals of the SpikeTrain

        Examples:
            >> st.spikes_times=[0, 2.1, 3.1, 4.4]
            >> st.isi()
                [2.1, 1., 1.3]

        See also
            cv_isi
        """
        return np.diff(self.spike_times)

    def mean_rate(self, t_start=None, t_stop=None):
        """
        Returns the mean firing rate between t_start and t_stop, in spikes/sec

        Inputs:
            t_start - in ms. If not defined, the one of the SpikeTrain object is used
            t_stop  - in ms. If not defined, the one of the SpikeTrain object is used

        Examples:
            >> spk.mean_rate()
                34.2
        """
        if (t_start is None) & (t_stop is None):
            t_start = self.t_start
            t_stop = self.t_stop
            idx = self.spike_times
        else:
            if t_start is None:
                t_start = self.t_start
            else:
                t_start = max(self.t_start, t_start)
            if t_stop is None:
                t_stop = self.t_stop
            else:
                t_stop = min(self.t_stop, t_stop)
            idx = np.where((self.spike_times >= t_start) & (self.spike_times <= t_stop))[0]
        return 1000. * len(idx) / (t_stop - t_start)

    def cv_isi(self):
        """
        Return the coefficient of variation of the isis.

        cv_isi is the ratio between the standard deviation and the mean of the ISI
          The irregularity of individual spike trains is measured by the squared
        coefficient of variation of the corresponding inter-spike interval (ISI)
        distribution normalized by the square of its mean.
          In point processes, low values reflect more regular spiking, a
        clock-like pattern yields CV2= 0. On the other hand, CV2 = 1 indicates
        Poisson-type behavior. As a measure for irregularity in the network_architect one
        can use the average irregularity across all neurons.

        http://en.wikipedia.org/wiki/Coefficient_of_variation

        See also
            isi, cv_kl

        """
        isi = self.isi()
        if len(isi) > 1:
            return np.std(isi)/np.mean(isi)
        else:
            return np.nan

    def cv_kl(self, bins=100):
        """
        Provides a measure for the coefficient of variation to describe the
        regularity in spiking networks. It is based on the Kullback-Leibler
        divergence and decribes the difference between a given
        interspike-interval-distribution and an exponential one (representing
        poissonian spike trains) with equal mean.
        It yields 1 for poissonian spike trains and 0 for regular ones.

        Reference:
            http://invibe.net/LaurentPerrinet/Publications/Voges08fens

        Inputs:
            bins - the number of bins used to gather the ISI

        Examples:
            > spklist.cv_kl(100)
                0.98

        See also:
            cv_isi
        """
        isi = self.isi() / 1000.
        if len(isi) < 2:
            return np.nan
        else:
            proba_isi, xaxis = np.histogram(isi, bins=bins, normed=True)
            xaxis = xaxis[:-1]
            proba_isi /= np.sum(proba_isi)
            bin_size = xaxis[1] - xaxis[0]
            # differential entropy: http://en.wikipedia.org/wiki/Differential_entropy
            KL = - np.sum(proba_isi * np.log(proba_isi + 1e-16)) + np.log(bin_size)
            KL -= -np.log(self.mean_rate()) + 1.
            CVkl = np.exp(-KL)
            return CVkl

    def fano_factor_isi(self):
        """
        Return the fano factor of this spike trains ISI.

        The Fano Factor is defined as the variance of the isi divided by the mean of the isi

        http://en.wikipedia.org/wiki/Fano_factor

        See also
            isi, cv_isi
        """
        isi = self.isi()
        if len(isi) > 1:
            fano = np.var(isi)/np.mean(isi)
            return fano
        else:
            raise Exception("No spikes in the SpikeTrain !")

    def autocorrelation(self):
        """
        Spike train autocorrelation as defined in:
        Kobayashi, R., Kitano, K. J Comput Neurosci 40, 347–362 (2016).
        https://doi.org/10.1007/s10827-016-0601-0
        :return:
        """
        n = len(self.isi())
        rho1 = []
        rho2 = []
        for iddx, nn in enumerate(self.isi()):
            if iddx > 1:
                rho1.append((self.isi()[iddx - 1] * nn) - np.mean(self.isi())**2.)
                rho2.append((nn**2.) - np.mean(self.isi())**2.)
        # print(np.mean(rho1), np.mean(rho2), np.mean(self.isi()))
        return np.mean(rho1) / np.mean(rho2)

    def time_axis(self, time_bin=10):
        """
        Return a time axis between t_start and t_stop according to a time_bin

        Inputs:
            time_bin - the bin width

        Examples:
            >> st = SpikeTrain(range(100),0.1,0,100)
            >> st.time_axis(10)
                [ 0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100]

        See also
            time_histogram
        """
        axis = np.arange(self.t_start, self.t_stop+time_bin, time_bin)
        return axis

    def time_offset(self, offset, return_new=False):
        """
        Add an offset to the SpikeTrain object. t_start and t_stop are
        shifted from offset, so does all the spike times.

        Inputs:
            offset - the time offset, in ms

        Examples:
            >> spktrain = SpikeTrain(arange(0,100,10))
            >> spktrain.time_offset(50)
            >> spklist.spike_times
                [  50.,   60.,   70.,   80.,   90.,  100.,  110.,
                120.,  130.,  140.]
        """
        if return_new:
            return SpikeTrain(self.spike_times + offset, self.t_start+offset, self.t_stop+offset)
        else:
            self.t_start += offset
            self.t_stop += offset
            self.spike_times += offset

    def time_slice(self, t_start, t_stop):
        """
        Return a new SpikeTrain obtained by slicing between t_start and t_stop,
        where t_start and t_stop may either be single values or sequences of
        start and stop times.

        Inputs:
            t_start - begining of the new SpikeTrain, in ms.
            t_stop  - end of the new SpikeTrain, in ms.

        Examples:
            >> spk = spktrain.time_slice(0,100)
            >> spk.t_start
                0
            >> spk.t_stop
                100
            >> spk = spktrain.time_slice([20,70], [40,90])
            >> spk.t_start
                20
            >> spk.t_stop
                90
            >> len(spk.time_slice(41, 69))
                0
        """
        if hasattr(t_start, '__len__'):
            if len(t_start) != len(t_stop):
                raise ValueError("t_start has %d values and t_stop %d. They must be of the same length." % (len(t_start), len(t_stop)))
            mask = False
            for t0, t1 in zip(t_start, t_stop):
                mask = mask | ((self.spike_times >= t0) & (self.spike_times <= t1))
            t_start = t_start[0]
            t_stop = t_stop[-1]
        else:
            mask = (self.spike_times >= t_start) & (self.spike_times <= t_stop)
        spikes = np.extract(mask, self.spike_times)
        return SpikeTrain(spikes, t_start, t_stop)

    def interval_slice(self, interval):
        """
        Return a new SpikeTrain obtained by slicing with an Interval. The new
        t_start and t_stop values of the returned SpikeTrain are the extrema of the Interval

        Inputs:
            interval - The interval from which spikes should be extracted

        Examples:
            >> spk = spktrain.time_slice(0,100)
            >> spk.t_start
                0
            >> spk.t_stop
                100
        """
        times = interval.slice_times(self.spike_times)
        t_start, t_stop = interval.time_parameters()
        return SpikeTrain(times, t_start, t_stop)

    def time_histogram(self, time_bin=10, normalized=True, binary=False):
        """
        Bin the spikes with the specified bin width. The first and last bins
        are calculated from `self.t_start` and `self.t_stop`.

        Inputs:
            time_bin   - the bin width for gathering spikes_times
            normalized - if True, the bin values are scaled to represent firing rates
                         in spikes/second, otherwise otherwise it's the number of spikes
                         per bin.
            binary     - if True, a binary matrix of 0/1 is returned

        Examples:
            >> st=SpikeTrain(range(0,100,5),0.1,0,100)
            >> st.time_histogram(10)
                [200, 200, 200, 200, 200, 200, 200, 200, 200, 200]
            >> st.time_histogram(10, normalized=False)
                [2, 2, 2, 2, 2, 2, 2, 2, 2, 2]

        See also
            time_axis
        """
        bins = self.time_axis(time_bin)
        hist, edges = np.histogram(self.spike_times, bins)
        hist = hist.astype(float)
        if normalized:  # what about normalization if time_bin is a sequence?
            hist *= 1000.0/float(time_bin)
        if binary:
            hist = hist.astype(bool).astype(int)
        return hist

    def fano_factor(self, time_bin=10):
        """
        Determine the fano factor for each spike
        :param time_bin:
        :return:
        """
        counts = self.time_histogram(time_bin=time_bin, normalized=False, binary=False)

        return np.var(counts) / np.mean(counts)

    def instantaneous_rate(self, resolution, kernel, norm, m_idx=None, t_start=None, t_stop=None, acausal=True,
                           trim=False):
        """
        Estimate instantaneous firing rate by kernel convolution.

        Inputs:
            resolution  - time stamp resolution of the spike times (ms). the
                          same resolution will be assumed for the kernel
            kernel      - kernel function used to convolve with
            norm        - normalization factor associated with kernel function
                          (see analysis.make_kernel for details)
            t_start     - start time of the interval used to compute the firing
                          rate
            t_stop      - end time of the interval used to compute the firing
                          rate (included)
            acausal     - if True, acausal filtering is used, i.e., the gravity
                          center of the filter function is aligned with the
                          spike to convolve
            m_idx       - index of the value in the kernel function vector that
                          corresponds to its gravity center. this parameter is
                          not mandatory for symmetrical kernels but it is
                          required when assymmetrical kernels are to be aligned
                          at their gravity center with the event times
            trim        - if True, only the 'valid' region of the convolved
                          signal are returned, i.e., the points where there
                          isn't complete overlap between kernel and spike train
                          are discarded
                          NOTE: if True and an assymetrical kernel is provided
                          the output will not be aligned with [t_start, t_stop]

        See also:
            analysis.make_kernel
        """

        if t_start is None:
            t_start = self.t_start

        if t_stop is None:
            t_stop = self.t_stop

        if m_idx is None:
            m_idx = kernel.size // 2

        time_vector = np.zeros((t_stop - t_start)//resolution + 1)

        spikes_slice = self.spike_times[(self.spike_times >= t_start) & (self.spike_times <= t_stop)]

        for spike in spikes_slice:
            index = (spike - t_start) // resolution
            time_vector[index] = 1

        r = norm * sp.fftconvolve(time_vector, kernel, 'full')

        if acausal is True:
            if trim is False:
                r = r[m_idx:-(kernel.size - m_idx)]
                t_axis = np.linspace(t_start, t_stop, r.size)
                return t_axis, r

            elif trim is True:
                r = r[2 * m_idx:-2*(kernel.size - m_idx)]
                t_start += m_idx * resolution
                t_stop -= (kernel.size - m_idx) * resolution
                t_axis = np.linspace(t_start, t_stop, r.size)
                return t_axis, r

        if acausal is False:
            if trim is False:
                r = r[m_idx:-(kernel.size - m_idx)]
                t_axis = (np.linspace(t_start, t_stop, r.size) + m_idx * resolution)
                return t_axis, r

            elif trim is True:
                r = r[2 * m_idx:-2*(kernel.size - m_idx)]
                t_start += m_idx * resolution
                t_stop -= ((kernel.size) - m_idx) * resolution
                t_axis = (np.linspace(t_start, t_stop, r.size) + m_idx * resolution)
                return t_axis, r

    def relative_times(self):
        """
        Rescale the spike times to make them relative to t_start.

        Note that the SpikeTrain object itself is modified, t_start
        is subtracted from spike_times, t_start and t_stop
        """
        if self.t_start != 0:
            self.spike_times -= self.t_start
            self.t_stop -= self.t_start
            self.t_start = 0.0

    def round_times(self, resolution=0.1):
        """
        Round the spike times to a given number of decimal places
        :param resolution:
        :return:
        """
        decimal_places = str(resolution)[::-1].find('.')
        self.spike_times = np.array([round(n, decimal_places) for n in self.spike_times])

    def distance_victorpurpura(self, spktrain, cost=0.5):
        """
        Function to calculate the Victor-Purpura distance between two spike trains.
        See J. D. Victor and K. P. Purpura,
            Nature and precision of temporal coding in visual cortex: a metric-space
            analysis.,
            J Neurophysiol,76(2):1310-1326, 1996

        Inputs:
            spktrain - the other SpikeTrain
            cost     - The cost parameter. See the paper for more information
        """
        nspk_1 = len(self)
        nspk_2 = len(spktrain)
        if cost == 0:
            return abs(nspk_1-nspk_2)
        elif cost > 1e9:
            return nspk_1+nspk_2
        scr = np.zeros((nspk_1+1, nspk_2+1))
        scr[:, 0] = np.arange(0, nspk_1+1)
        scr[0, :] = np.arange(0, nspk_2+1)

        if nspk_1 > 0 and nspk_2 > 0:
            for i in range(1, nspk_1+1):
                for j in range(1, nspk_2+1):
                    scr[i, j] = min(scr[i-1, j]+1, scr[i, j-1]+1)
                    scr[i, j] = min(scr[i, j], scr[i-1, j-1]+cost*abs(self.spike_times[i-1]-spktrain.spike_times[j-1]))
        return scr[nspk_1, nspk_2]

    def distance_kreuz(self, spktrain, dt=0.1):
        """
        Function to calculate the Kreuz/Politi distance between two spike trains
        See  Kreuz, T.; Haas, J.S.; Morelli, A.; Abarbanel, H.D.I. & Politi, A.
            Measuring spike train synchrony.
            J Neurosci Methods, 165:151-161, 2007

        Inputs:
            spktrain - the other SpikeTrain
            dt       - the bin width used to discretize the spike times

        Examples:
            >> spktrain.KreuzDistance(spktrain2)

        See also
            VictorPurpuraDistance
        """
        N = (self.t_stop-self.t_start)//dt
        vec_1 = np.zeros(N, np.float32)
        vec_2 = np.zeros(N, np.float32)
        result = np.zeros(N, float)
        idx_spikes = np.array(self.spike_times/dt, int)
        previous_spike = 0
        if len(idx_spikes) > 0:
            for spike in idx_spikes[1:]:
                vec_1[previous_spike:spike] = (spike-previous_spike)
                previous_spike = spike
        idx_spikes = np.array(spktrain.spike_times/dt, int)
        previous_spike = 0
        if len(idx_spikes) > 0:
            for spike in idx_spikes[1:]:
                vec_2[previous_spike:spike] = (spike-previous_spike)
                previous_spike = spike
        idx = np.where(vec_1 < vec_2)[0]
        result[idx] = vec_1[idx]/vec_2[idx] - 1
        idx = np.where(vec_1 > vec_2)[0]
        result[idx] = -vec_2[idx]/vec_1[idx] + 1
        return np.sum(np.abs(result))/len(result)

    def psth(self, events, time_bin=2, t_min=50, t_max=50, average=True):
        """
        Return the psth of the spike times contained in the SpikeTrain according to selected events,
        on a time window t_spikes - tmin, t_spikes + tmax

        Inputs:
            events  - Can be a SpikeTrain object (and events will be the spikes) or just a list
                      of times
            time_bin- The time bin (in ms) used to gather the spike for the psth
            t_min   - Time (>0) to average the signal before an event, in ms (default 0)
            t_max   - Time (>0) to average the signal after an event, in ms  (default 100)

        Examples:
            >> spk.psth(spktrain, t_min = 50, t_max = 150)
            >> spk.psth(spktrain, )

        See also
            SpikeTrain.spike_histogram
        """

        if isinstance(events, SpikeTrain):
            events = events.spike_times
        assert (t_min >= 0) and (t_max >= 0), "t_min and t_max should be greater than 0"
        assert len(events) > 0, "events should not be empty and should contained at least one element"

        spk_hist = self.time_histogram(time_bin)
        count = 0
        t_min_l = np.floor(t_min / time_bin)
        t_max_l = np.floor(t_max / time_bin)
        result = np.zeros((t_min_l + t_max_l), np.float32)
        t_start = np.floor(self.t_start / time_bin)
        t_stop = np.floor(self.t_stop / time_bin)
        result = []
        for ev in events:
            ev = np.floor(ev / time_bin)
            if ((ev - t_min_l) > t_start) and (ev + t_max_l) < t_stop:
                count += 1
                result += [spk_hist[(ev - t_min_l):ev + t_max_l]]
        result = np.array(result)
        if average:
            result /= count
        return result

    def lv(self):
        """
        Coefficient of local variation
        :return:
        """
        # convert to array, cast to float
        v = self.isi()

        # ensure we have enough entries
        if v.size < 2:
            return np.nan
        # calculate LV and return result
        else:
            #  raise error if input is multi-dimensional
            return 3. * np.mean(np.power(np.diff(v) / (v[:-1] + v[1:]), 2))

    def lv_r(self, R=2.):
        """
        Revised local variation coefficient
        Based on Shinomoto, S. et al., PLoS Comp.Bio., Relating firing patterns to Functional differentiation...
        :param R: Refractory time
        :return:
        """
        # convert to array, cast to float
        v = self.isi()

        # ensure we have enough entries
        if v.size < 2:
            return np.nan
        # calculate LV and return result
        else:
            sum_lvr = 0.
            for i in range(len(v) - 1):
                sum_lvr += ((v[i] - v[i + 1]) ** 2.) / ((v[i] + v[i + 1] - 2 * R) ** 2)
            return 3. / (len(v) - 1) * sum_lvr

    # #######################################################################
    # # Plotting routines that can be applied to a SpikeTrain object        #
    # #######################################################################
    # def raster_plot(self, ax=None, t_start=None, t_stop=None, save=False, display=True):
    #     """
    #     Plot the spike times of a single SpikeTrain as a vertical line
    #     :param ax:
    #     :param t_start:
    #     :param t_stop:
    #     :param save:
    #     :param display:
    #     :return:
    #     """
    #     if t_start is None:
    #         t_start = self.t_start
    #     if t_stop is None:
    #         t_stop = self.t_stop
    #     vis.plotting.plot_single_raster(self.spike_times, ax, t_start, t_stop, save=save, display=display)
    #
    # def plot_isi_distribution(self, ax=None, save=False, display=True, **kwargs):
    #     """
    #     Plot the distribution of inter-spike-intervals
    #     :return:
    #     """
    #     vis.plotting.plot_isis(self.isi(), ax, save=save, display=display, **kwargs)


# ######################################################################################################################
class SpikeList(object):
    """
    SpikeList(spikes, id_list, t_start=None, t_stop=None, dims=None)

    Return a SpikeList object which will be a list of SpikeTrain objects.

    Inputs:
        spikes  - a list of (id,time) tuples (id being in id_list)
        id_list - the list of the ids of all recorded cells (needed for silent cells)
        t_start - begining of the SpikeList, in ms. If None, will be infered from the data
        t_stop  - end of the SpikeList, in ms. If None, will be infered from the data
        dims    - dimensions of the recorded population, if not 1D population

    t_start and t_stop are shared for all SpikeTrains object within the SpikeList

    Examples:
        >> sl = SpikeList([(0, 0.1), (1, 0.1), (0, 0.2)], range(2))
        >> type( sl[0] )
            <type SpikeTrain>

    See also
        load_spikelist
    """
    def __init__(self, spikes, id_list, t_start=None, t_stop=None, dims=None):
        """
        Constructor of the SpikeList object

        See also
            SpikeList, load_spikelist
        """
        self.t_start 	 = t_start
        self.t_stop 	 = t_stop
        self.dimensions  = dims
        self.spiketrains = {}
        id_list = np.sort(id_list)

        # set dimension explicitly if needed
        if self.dimensions is None:
            self.dimensions = len(id_list)

        if not isinstance(spikes, np.ndarray):
            spikes = np.array(spikes, np.float32)
            # circumvents numpy floating point magic that leads to filtering errors..
        N = len(spikes)

        if N > 0:
            idx = np.argsort(spikes[:, 0])
            spikes = spikes[idx]
            break_points = np.where(np.diff(spikes[:, 0]) > 0)[0] + 1
            break_points = np.concatenate(([0], break_points))
            break_points = np.concatenate((break_points, [N]))
            for idx in range(len(break_points)-1):
                id = spikes[break_points[idx], 0]
                if id in id_list:
                    self.spiketrains[id] = SpikeTrain(spikes[break_points[idx]:break_points[idx+1], 1], self.t_start, self.t_stop)

        # self.complete(id_list)
        # TODO - test complete with range(N)

        if len(self) > 0 and (self.t_start is None or self.t_stop is None):
            self.__calc_startstop()
            del spikes

    def __del__(self):
        for id in self.id_list:
            del self.spiketrains[id]

    @property
    def id_list(self):
        """
        Return the list of all the cells ids contained in the
        SpikeList object

        Examples
            >> spklist.id_list
            [0,1,2,3,....,9999]
        """
        return np.array(list(self.spiketrains.keys()), int)

    def copy(self):
        """
        Return a copy of the SpikeList object
        """
        spklist = SpikeList([], [], self.t_start, self.t_stop, self.dimensions)
        for id in self.id_list:
            spklist.append(id, self.spiketrains[id])
        return spklist

    def __calc_startstop(self, t_start=None, t_stop=None):
        """
        t_start and t_stop are shared for all neurons, so we take min and max values respectively.
        """
        if len(self) > 0:
            if t_start is not None:
                self.t_start = t_start
                for id in list(self.spiketrains.keys()):
                    self.spiketrains[id].t_start = t_start

            elif self.t_start is None:
                start_times = np.array([self.spiketrains[idx].t_start for idx in self.id_list], np.float32)
                self.t_start = np.min(start_times)
                for id in list(self.spiketrains.keys()):
                    self.spiketrains[id].t_start = self.t_start
            if t_stop is not None:
                self.t_stop = t_stop
                for id in list(self.spiketrains.keys()):
                    self.spiketrains[id].t_stop = t_stop
            elif self.t_stop is None:
                stop_times = np.array([self.spiketrains[idx].t_stop for idx in self.id_list], np.float32)
                self.t_stop = np.max(stop_times)
                for id in list(self.spiketrains.keys()):
                    self.spiketrains[id].t_stop = self.t_stop
        else:
            raise Exception("No SpikeTrains")

    def __getitem__(self, id):
        if id in self.id_list:
            return self.spiketrains[id]
        else:
            raise Exception("id %d is not present in the SpikeList. See id_list" %id)

    def __getslice__(self, i, j):
        """
        Return a new SpikeList object with all the ids between i and j
        """
        ids = np.where((self.id_list >= i) & (self.id_list < j))[0]
        return self.id_slice(ids)

    def __setitem__(self, id, spktrain):
        assert isinstance(spktrain, SpikeTrain), "A SpikeList object can only contain SpikeTrain objects"
        self.spiketrains[id] = spktrain
        self.__calc_startstop()

    def __iter__(self):
        return iter(self.spiketrains.values())

    def __len__(self):
        return len(self.spiketrains)

    def __sub_id_list(self, sub_list=None):
        """
        Internal function used to get a sublist for the Spikelist id list

        Inputs:
            sublist - can be an int (and then N random cells are selected). Otherwise
                    sub_list is a list of cell in self.id_list. If None, id_list is returned

        Examples:
            >> self.__sub_id_list(50)
        """
        if sub_list is None:
            return self.id_list
        elif type(sub_list) == int:
            return np.random.permutation(self.id_list)[0:sub_list]
        else:
            return sub_list

    def __select_with_pairs__(self, nb_pairs, pairs_generator):
        """
        Internal function used to slice two SpikeList according to a list
        of pairs.  Return a list of pairs

        Inputs:
            nb_pairs        - an int specifying the number of cells desired
            pairs_generator - a pairs generator

        Examples:
            >> self.__select_with_pairs__(50, RandomPairs(spk1, spk2))

        See also
            RandomPairs, AutoPairs, CustomPairs
        """
        pairs = pairs_generator.get_pairs(nb_pairs)
        spk1 = pairs_generator.spk1.id_slice(pairs[:, 0])
        spk2 = pairs_generator.spk2.id_slice(pairs[:, 1])
        return spk1, spk2, pairs

    def append(self, id, spktrain):
        """
        Add a SpikeTrain object to the SpikeList

        Inputs:
            id       - the id of the new cell
            spktrain - the SpikeTrain object representing the new cell

        The SpikeTrain object is sliced according to the t_start and t_stop times
        of the SpikeLlist object

        Examples
            >> st=SpikeTrain(range(0,100,5),0.1,0,100)
            >> spklist.append(999, st)
                spklist[999]

        See also
            concatenate, __setitem__
        """
        assert isinstance(spktrain, SpikeTrain), "A SpikeList object can only contain SpikeTrain objects"
        if id in self.id_list:
            raise Exception("id %d already present in SpikeList. Use __setitem__ (spk[id]=...) instead()" % id)
        else:
            self.spiketrains[id] = spktrain.time_slice(self.t_start, self.t_stop)

    def time_parameters(self):
        """
        Return the time parameters of the SpikeList (t_start, t_stop)
        """
        return (self.t_start, self.t_stop)

    def jitter(self, jitter):
        """
        Returns a new SpikeList with spiketimes jittered by a normal distribution.

        Inputs:
            jitter - sigma of the normal distribution

        Examples:
            >> st_jittered = st.jitter(2.0)
        """
        new_SpkList = SpikeList([], [], self.t_start, self.t_stop, self.dimensions)
        for id in self.id_list:
            new_SpkList.append(id, self.spiketrains[id].jitter(jitter))
        return new_SpkList

    def round_times(self, resolution):
        """

        :param resolution:
        :return:
        """
        for id, spiketrain in list(self.spiketrains.items()):
            spiketrain.round_times(resolution)

    def time_axis(self, time_bin):
        """
        Return a time axis between t_start and t_stop according to a time_bin

        Inputs:
            time_bin - the bin width

        See also
            spike_histogram
        """
        axis = np.arange(self.t_start, self.t_stop+time_bin, time_bin)
        return axis

    def concatenate(self, spklists):
        """
        Concatenation of SpikeLists to the current SpikeList.

        Inputs:
            spklists - could be a single SpikeList or a list of SpikeLists

        The concatenated SpikeLists must have similar (t_start, t_stop), and
        they can't shared similar cells. All their ids have to be different.

        See also
        append, merge, __setitem__
        """
        if isinstance(spklists, SpikeList):
            spklists = [spklists]
        # We check that Spike Lists have similar time_axis
        for sl in spklists:
            if not sl.time_parameters() == self.time_parameters():
                raise Exception("Spike Lists should have similar time_axis (t_start and t_stop)!")
        for sl in spklists:
            for id in sl.id_list:
                self.append(id, sl.spiketrains[id])

    def merge(self, spikelist, relative=False):
        """
        For each cell id in spikelist that matches an id in this SpikeList,
        merge the two SpikeTrains and save the result in this SpikeList.
        Note that SpikeTrains with ids not in this SpikeList are appended to it.

        Inputs:
            spikelist - the SpikeList that should be merged to the current one
            relative  - if True, spike times are expressed in a relative
                        time compared to the previsous one

        Examples:
            >> spklist.merge(spklist2)

        See also:
            concatenate, append, __setitem__
        """
        for id, spiketrain in list(spikelist.spiketrains.items()):
            if id in self.id_list:
                self.spiketrains[id].merge(spiketrain, relative)
            else:
                if relative:
                    spiketrain.relative_times()
                self.append(id, spiketrain)
        self.__calc_startstop(t_stop=self.last_spike_time())

    def complete(self, id_list):
        """
        Complete the SpikeList by adding empty SpikeTrain for all the ids present in
        ids that are not already in the SpikeList

         Inputs:
            id_list - The id_list that should be completed

        Examples:
            >> spklist.id_list
                [0,2,5]
            >> spklist.complete(arange(5))
            >> spklist.id_list
                [0,1,2,3,4]
        """
        id_list = set(id_list)
        missing_ids = id_list.difference(set(self.id_list))
        for id in missing_ids:
            self.append(id, SpikeTrain([], self.t_start, self.t_stop))

    def id_slice(self, id_list):
        """
        Return a new SpikeList obtained by selecting particular ids

        Inputs:
            id_list - Can be an integer (and then N random cells will be selected)
                      or a sublist of the current ids

        The new SpikeList inherits the time parameters (t_start, t_stop)

        Examples:
            >> spklist.id_list
                [830, 1959, 1005, 416, 1011, 1240, 729, 59, 1138, 259]
            >> new_spklist = spklist.id_slice(5)
            >> new_spklist.id_list
                [1011, 729, 1138, 416, 59]

        See also
            time_slice, interval_slice
        """
        new_SpkList = SpikeList([], [], self.t_start, self.t_stop, self.dimensions)
        id_list = self.__sub_id_list(id_list)
        new_SpkList.dimensions = len(id_list)  # update dimension of new spike list

        for id_ in id_list:
            try:
                new_SpkList.append(id_, self.spiketrains[id_])
            except Exception:
                print("id %d is not in the source SpikeList or already in the new one" % id_)
        return new_SpkList

    def time_slice(self, t_start, t_stop):
        """
        Return a new SpikeList obtained by slicing between t_start and t_stop

        Inputs:
            t_start - begining of the new SpikeTrain, in ms.
            t_stop  - end of the new SpikeTrain, in ms.

        See also
            id_slice, interval_slice
        """
        new_SpkList = SpikeList([], [], t_start, t_stop, self.dimensions)
        for id in self.id_list:
            new_SpkList.append(id, self.spiketrains[id].time_slice(t_start, t_stop))
        new_SpkList.__calc_startstop()
        return new_SpkList

    def interval_slice(self, interval):
        """
        Return a new SpikeList obtained by slicing with an Interval. The new
        t_start and t_stop values of the returned SpikeList are the extrema of the Interval

        Inputs:
            interval - The Interval to slice with

        See also
            id_slice, time_slice
        """
        t_start, t_stop = interval.time_parameters()
        new_SpkList = SpikeList([], [], t_start, t_stop, self.dimensions)
        for id in self.id_list:
            new_SpkList.append(id, self.spiketrains[id].interval_slice(interval))
        return new_SpkList

    def time_offset(self, offset, new_spikeList=False):
        """
        Add an offset to the whole SpikeList object. t_start and t_stop are
        shifted from offset, so does all the SpikeTrain.

        Inputs:
            offset - the time offset, in ms

        Examples:
            >> spklist.t_start
                1000
            >> spklist.time_offset(50)
            >> spklist.t_start
                1050
        """
        if new_spikeList:
            new_SpkList = SpikeList([], [], self.t_start+offset, self.t_stop+offset, self.dimensions)
            for id in self.id_list:
                new_SpkList.append(id, self.spiketrains[id].time_offset(offset, True))
            return new_SpkList
        else:
            self.t_start += offset
            self.t_stop += offset
            for id in self.id_list:
                self.spiketrains[id].time_offset(offset)

    def id_offset(self, offset):
        """
        Add an offset to the whole SpikeList object. All the id are shifted
        according to an offset value.

        Inputs:
            offset - the id offset

        Examples:
            >> spklist.id_list
                [0,1,2,3,4]
            >> spklist.id_offset(10)
            >> spklist.id_list
                [10,11,12,13,14]
        """
        id_list = np.sort(self.id_list)
        N = len(id_list)
        if offset > 0:
            for idx in range(1, len(id_list)+1):
                id = id_list[N - idx]
                spk = self.spiketrains.pop(id)
                self.spiketrains[id + offset] = spk
        if offset < 0:
            for idx in range(0, len(id_list)):
                id  = id_list[idx]
                spk = self.spiketrains.pop(id)
                self.spiketrains[id + offset] = spk

    def first_spike_time(self):
        """
        Get the time of the first real spike in the SpikeList
        """
        first_spike = self.t_stop
        is_empty = True
        for id in self.id_list:
            if len(self.spiketrains[id]) > 0:
                is_empty = False
                if self.spiketrains[id].spike_times[0] < first_spike:
                    first_spike = self.spiketrains[id].spike_times[0]
                    #print id, first_spike
        if is_empty:
            raise Exception("No spikes can be found in the SpikeList object !")
        else:
            return first_spike

    def last_spike_time(self):
        """
        Get the time of the last real spike in the SpikeList
        """
        last_spike = self.t_start
        is_empty = True
        for id in self.id_list:
            if len(self.spiketrains[id]) > 0:
                is_empty = False
                if self.spiketrains[id].spike_times[-1] > last_spike:
                    last_spike = self.spiketrains[id].spike_times[-1]
        if is_empty:
            raise Exception("No spikes can be found in the SpikeList object !")
        else:
            return last_spike

    def select_ids(self, criteria):
        """
        Return the list of all the cells in the SpikeList that will match the criteria
        expressed with the following syntax.

        Inputs :
            criteria - a string that can be evaluated on a SpikeTrain object, where the
                       SpikeTrain should be named ``cell''.

        Examples:
            >> spklist.select_ids("cell.mean_rate() > 0") (all the active cells)
            >> spklist.select_ids("cell.mean_rate() == 0") (all the silent cells)
            >> spklist.select_ids("len(cell.spike_times) > 10")
            >> spklist.select_ids("mean(cell.isi()) < 1")
        """
        selected_ids = []
        for id in self.id_list:
            cell = self.spiketrains[id]
            if eval(criteria):
                selected_ids.append(id)
        return selected_ids

    def empty(self):
        """
        Checks if SpikeList object has any spikes.
        :return: True, if all spiketrains are empty, False otherwise
        """
        return not any([len(st) for idx, st in self.spiketrains.items()])

    #######################################################################
    # Analysis methods that can be applied to a SpikeTrain object         #
    #######################################################################
    def isi(self):
        """
        Return the list of all the isi vectors for all the SpikeTrains objects
        within the SpikeList.

        See also:
            isi_hist
        """
        isis = []
        for id_ in self.id_list:
            isis.append(self.spiketrains[id_].isi())
        return isis

    def cv_isi(self, float_only=False):
        """
        Return the list of all the CV coefficients for each SpikeTrains object
        within the SpikeList. Return NaN when not enough spikes are present

        Inputs:
            float_only - False by default. If true, NaN values are automatically
                         removed

        Examples:
            >> spklist.cv_isi()
                [0.2,0.3,Nan,2.5,Nan,1.,2.5]
            >> spklist.cv_isi(True)
                [0.2,0.3,2.5,1.,2.5]

        See also:
            cv_isi_hist, cv_local, cv_kl, SpikeTrain.cv_isi

        """
        ids = self.id_list
        N = len(ids)
        cvs_isi = np.empty(N)
        for idx in range(N):
            cvs_isi[idx] = self.spiketrains[ids[idx]].cv_isi()

        if float_only:
            cvs_isi = np.extract(np.logical_not(np.isnan(cvs_isi)), cvs_isi)
            cvs_isi = np.extract(np.logical_not(np.isinf(cvs_isi)), cvs_isi)
        return cvs_isi

    def cv_kl(self, bins=50, float_only=False):
        """
        Return the list of all the CV coefficients for each SpikeTrains object
        within the SpikeList. Return NaN when not enough spikes are present

        Inputs:
            bins       - The number of bins used to gathered the ISI
            float_only - False by default. If true, NaN values are automatically
                         removed

        Examples:
            >> spklit.cv_kl(50)
                [0.4, Nan, 0.9, nan]
            >> spklist.cv_kl(50, True)
                [0.4, 0.9]

        See also:
            cv_isi_hist, cv_local, cv_isi, SpikeTrain.cv_kl
        """
        ids = self.id_list
        N = len(ids)
        cvs_kl = np.empty(N)
        for idx in range(N):
            cvs_kl[idx] = self.spiketrains[ids[idx]].cv_kl(bins=bins)

        if float_only:
            cvs_kl = np.extract(np.logical_not(np.isnan(cvs_kl)), cvs_kl)
            cvs_kl = np.extract(np.logical_not(np.isinf(cvs_kl)), cvs_kl)
        return cvs_kl

    def mean_rate(self, t_start=None, t_stop=None):
        """
        Return the mean firing rate averaged across all SpikeTrains between t_start and t_stop.

        Inputs:
            t_start - begining of the selected area to compute mean_rate, in ms
            t_stop  - end of the selected area to compute mean_rate, in ms

        If t_start or t_stop are not defined, those of the SpikeList are used

        Examples:
            >> spklist.mean_rate()
            >> 12.63

        See also
            mean_rates, mean_rate_std
        """
        return np.mean(self.mean_rates(t_start, t_stop))

    def mean_rate_std(self, t_start=None, t_stop=None):
        """
        Standard deviation of the firing rates across all SpikeTrains
        between t_start and t_stop

        Inputs:
            t_start - beginning of the selected area to compute std(mean_rate), in ms
            t_stop  - end of the selected area to compute std(mean_rate), in ms

        If t_start or t_stop are not defined, those of the SpikeList are used

        Examples:
            >> spklist.mean_rate_std()
            >> 13.25

        See also
            mean_rate, mean_rates
        """
        return np.std(self.mean_rates(t_start, t_stop))

    def mean_rates(self, t_start=None, t_stop=None):
        """
        Returns a vector of the size of id_list giving the mean firing rate for each neuron

        Inputs:
            t_start - beginning of the selected area to compute std(mean_rate), in ms
            t_stop  - end of the selected area to compute std(mean_rate), in ms

        If t_start or t_stop are not defined, those of the SpikeList are used

        See also
            mean_rate, mean_rate_std
        """
        rates = []
        for id in self.id_list:
            rates.append(self.spiketrains[id].mean_rate(t_start, t_stop))
        return rates

    def spike_histogram(self, time_bin, normalized=False, binary=False):
        """
        Generate an array with all the spike_histograms of all the SpikeTrains
        objects within the SpikeList.

        Inputs:
            time_bin   - the time bin used to gather the data
            normalized - if True, the histogram are in Hz (spikes/second), otherwise they are
                         in spikes/bin
            binary     - if True, a binary matrix of 0/1 is returned

        See also
            firing_rate, time_axis
        """
        nbins = self.time_axis(time_bin)
        N = len(self)
        M = len(nbins) - 1               # nbins are the bin edges, so M must correct for this...
        if binary:
            spike_hist = np.zeros((N, M), np.int)
        else:
            spike_hist = np.zeros((N, M), np.float32)

        for idx, id in enumerate(self.id_list):
            hist, edges = np.histogram(self.spiketrains[id].spike_times, nbins)
            hist = hist.astype(float)
            if normalized:
                hist *= 1000.0 / float(time_bin)
            if binary:
                hist = hist.astype(bool)
            spike_hist[idx, :] = hist
        return spike_hist

    def firing_rate(self, time_bin, average=False, binary=False):
        """
        Generate an array with all the instantaneous firing rates along time (in Hz)
        of all the SpikeTrains objects within the SpikeList. If average is True, it gives the
        average firing rate over the whole SpikeList

        Inputs:
            time_bin   - the time bin used to gather the data
            average    - If True, return a single vector of the average firing rate over the whole SpikeList
            binary     - If True, a binary matrix with 0/1 is returned.

        See also
            spike_histogram, time_axis
        """
        result = self.spike_histogram(time_bin, normalized=True, binary=binary)
        if average:
            return np.mean(result, axis=0)
        else:
            return result

    def averaged_instantaneous_rate(self, resolution, kernel, norm, m_idx=None,
                                    t_start=None, t_stop=None, acausal=True,
                                    trim=False):
        """
        Estimate the instantaneous firing rate averaged across neurons in the
        SpikeList, by kernel density estimation.

        Inputs:
            resolution  - time stamp resolution of the spike times (ms). the
                          same resolution will be assumed for the kernel
            kernel      - kernel function used to convolve with
            norm        - normalization factor associated with kernel function
                          (see analysis.make_kernel for details)
            t_start     - start time of the interval used to compute the firing
                          rate
            t_stop      - end time of the interval used to compute the firing
                          rate (included)
            acausal     - if True, acausal filtering is used, i.e., the gravity
                          center of the filter function is aligned with the
                          spike to convolve
            m_idx       - index of the value in the kernel function vector that
                          corresponds to its gravity center. this parameter is
                          not mandatory for symmetrical kernels but it is
                          required when assymmetrical kernels are to be aligned
                          at their gravity center with the event times
            trim        - if True, only the 'valid' region of the convolved
                          signal are returned, i.e., the points where there
                          isn't complete overlap between kernel and spike train
                          are discarded
                          NOTE: if True and an assymetrical kernel is provided
                          the output will not be aligned with [t_start, t_stop]

        See also:
            analysis.make_kernel, SpikeTrain.instantaneous_rate
        """

        if t_start is None:
            t_start = self.t_start

        if t_stop is None:
            t_stop = self.t_stop

        if m_idx is None:
            m_idx = kernel.size // 2

        spikes_slice = []
        for i in self:
            train_slice = i.spike_times[(i.spike_times >= t_start) & (
            i.spike_times <= t_stop)]
            spikes_slice += train_slice.tolist()

        time_vector = np.zeros((t_stop - t_start) // resolution + 1)

        for spike in spikes_slice:
            index = (spike - t_start) // resolution
            time_vector[index] += 1.

        avg_time_vector = time_vector / float(self.id_list.size)

        r = norm * sp.fftconvolve(avg_time_vector, kernel, 'full')

        if acausal is True:
            if trim is False:
                r = r[m_idx:-(kernel.size - m_idx)]
                t_axis = np.linspace(t_start, t_stop, r.size)
                return t_axis, r

            elif trim is True:
                r = r[2 * m_idx:-2 * (kernel.size - m_idx)]
                t_start += m_idx * resolution
                t_stop -= ((kernel.size) - m_idx) * resolution
                t_axis = np.linspace(t_start, t_stop, r.size)
                return t_axis, r

        if acausal is False:
            if trim is False:
                r = r[m_idx:-(kernel.size - m_idx)]
                t_axis = (np.linspace(t_start, t_stop, r.size) + m_idx * resolution)
                return t_axis, r

            elif trim is True:
                r = r[2 * m_idx:-2 * (kernel.size - m_idx)]
                t_start += m_idx * resolution
                t_stop -= (kernel.size - m_idx) * resolution
                t_axis = (np.linspace(t_start, t_stop, r.size) + m_idx * resolution)
                return t_axis, r

    def fano_factor(self, time_bin):
        """
        Compute the Fano Factor of the population activity.

        Inputs:
            time_bin   - the number of bins (between the min and max of the data)
                         or a list/array containing the lower edges of the bins.

        The Fano Factor is computed as the variance of the averaged activity divided by its
        mean

        See also
            spike_histogram, firing_rate
        """
        firing_rate = self.spike_histogram(time_bin)
        firing_rate = np.mean(firing_rate, axis=0)
        fano        = np.var(firing_rate) / np.mean(firing_rate)
        return fano

    def fano_factors(self, time_bin):
        """
        Compute all the fano factors of the individual neuron's spike counts
        """
        ffs = []
        for nn in self.spiketrains:
            ff = self.spiketrains[nn].fano_factor(time_bin=time_bin)
            ffs.append(ff)
        return ffs

    def fano_factors_isi(self):
        """
        Return a list containing the fano factors for each neuron

        See also
            isi, isi_cv
        """
        fano_factors = []
        for id in self.id_list:
            try:
                fano_factors.append(self.spiketrains[id].fano_factor_isi())
            except:
                pass

        return fano_factors

    def autocorrelations(self, float_only=True):
        """
        Returns isi adaptation index for all neurons in spikelist
        :return:
        """
        ai = [self.spiketrains[v].autocorrelation() for v in self.id_list if len(self.spiketrains[v]) > 1]
        if float_only:
            ai = np.extract(np.logical_not(np.isnan(ai)), ai)
        return np.array(ai)

    def local_variation(self, float_only=True):
        """
        Local isi variation (see e.g. Shinomoto (2009))
        :param float_only:
        :return:
        """
        lvs = [self.spiketrains[v].lv() for v in self.id_list]

        if float_only:
            lvs = np.extract(np.logical_not(np.isnan(lvs)), lvs)
            lvs = np.extract(np.logical_not(np.isinf(lvs)), lvs)
        return lvs

    def local_variation_revised(self, float_only=True):
        # TODO: variable refractory time
        lvs = [self.spiketrains[v].lv_r() for v in self.id_list]

        if float_only:
            lvs = np.extract(np.logical_not(np.isnan(lvs)), lvs)
            lvs = np.extract(np.logical_not(np.isinf(lvs)), lvs)
        return lvs

    def instantaneous_regularity(self, float_only=True):
        """

        :param spike_list:
        :param float_only:
        :return:
        """
        iR = [self.spiketrains[n].ir() for n in self.id_list]
        if float_only:
            iR = np.extract(np.logical_not(np.isnan(iR)), iR)
            iR = np.extract(np.logical_not(np.isinf(iR)), iR)
        return iR

    @staticmethod
    def _summed_dist_matrix(spiketrains, tau):
        # The algorithm underlying this implementation is described in
        # Houghton, C., & Kreuz, T. (2012). On the efficient calculation of van
        # Rossum distances. Network: Computation in Neural Systems, 23(1-2),
        # 48-58.
        # Given N spiketrains with n entries on average the run-time complexity is
        # O(N^2 * n). O(N^2 + N * n) memory will be needed.

        if len(spiketrains) <= 0:
            return np.zeros((0, 0))

        sizes = np.asarray([len(v) for v in spiketrains])
        values = np.empty((len(spiketrains), max(1, sizes.max())))
        values.fill(np.nan)
        for i, v in enumerate(spiketrains):
            if len(v) > 0:
                values[i, :len(v)] = (v.spike_times / tau)

        exp_diffs = np.exp(values[:, :-1] - values[:, 1:])
        markage = np.zeros(values.shape)
        for u in range(len(spiketrains)):
            markage[u, 0] = 0
            for i in range(sizes[u] - 1):
                markage[u, i + 1] = (markage[u, i] + 1.0) * exp_diffs[u, i]

        # Same spiketrain terms
        D = np.empty((len(spiketrains), len(spiketrains)))
        D[np.diag_indices_from(D)] = sizes + 2.0 * np.sum(markage, axis=1)

        # Cross spiketrain terms
        for u in range(D.shape[0]):
            all_ks = np.searchsorted(values[u], values, 'left') - 1
            for v in range(u):
                js = np.searchsorted(values[v], values[u], 'right') - 1
                ks = all_ks[v]
                slice_j = np.s_[np.searchsorted(js, 0):sizes[u]]
                slice_k = np.s_[np.searchsorted(ks, 0):sizes[v]]
                D[u, v] = np.sum(
                    np.exp(values[v][js[slice_j]] - values[u][slice_j]) *
                    (1.0 + markage[v][js[slice_j]]))
                D[u, v] += np.sum(
                    np.exp(values[u][ks[slice_k]] - values[v][slice_k]) *
                    (1.0 + markage[u][ks[slice_k]]))
                D[v, u] = D[u, v]

        return D

    def distance_van_rossum(self, tau=1.0):
        """
        Calculates the van Rossum distance.

        It is defined as Euclidean distance of the spike trains convolved with a
        causal decaying exponential smoothing filter. A detailed description can
        be found in *Rossum, M. C. W. (2001). A novel spike distance. Neural
        Computation, 13(4), 751-763.* This implementation is normalized to yield
        a distance of 1.0 for the distance between an empty spike train and a
        spike train with a single spike. Divide the result by sqrt(2.0) to get
        the normalization used in the cited paper.

        Given :math:`N` spike trains with :math:`n` spikes on average the run-time
        complexity of this function is :math:`O(N^2 n)`.

        Parameters
        ----------
        trains : Sequence of :class:`neo.core.SpikeTrain` objects of
            which the van Rossum distance will be calculated pairwise.
        tau : Quantity scalar
            Decay rate of the exponential function as time scalar. Controls for
            which time scale the metric will be sensitive. This parameter will
            be ignored if `kernel` is not `None`. May also be :const:`scipy.inf`
            which will lead to only measuring differences in spike count.
            Default: 1.0 * pq.s
        sort : bool
            Spike trains with sorted spike times might be needed for the
            calculation. You can set `sort` to `False` if you know that your
            spike trains are already sorted to decrease calculation time.
            Default: True

        Returns
        -------
            2-D array
            Matrix containing the van Rossum distances for all pairs of
            spike trains.

        Example
        -------
            import elephant.spike_train_dissimilarity_measures as stdm
            tau = 10.0 * pq.ms
            st_a = SpikeTrain([10, 20, 30], units='ms', t_stop= 1000.0)
            st_b = SpikeTrain([12, 24, 30], units='ms', t_stop= 1000.0)
            vr   = stdm.van_rossum_dist([st_a, st_b], tau)[0, 1]
        """
        if tau == 0:
            spike_counts = [len(st) for st in self.spiketrains]
            return np.sqrt(spike_counts + np.atleast_2d(spike_counts).T)
        elif tau == np.inf:
            spike_counts = [len(st) for st in self.spiketrains]
            return np.absolute(spike_counts - np.atleast_2d(spike_counts).T)

        k_dist = self._summed_dist_matrix([st for st in list(self.spiketrains.values())], tau)
        vr_dist = np.empty_like(k_dist)
        for i, j in np.ndindex(k_dist.shape):
            vr_dist[i, j] = (
                k_dist[i, i] + k_dist[j, j] - k_dist[i, j] - k_dist[j, i])
        return np.sqrt(vr_dist)

    def pairwise_cc(self, nb_pairs, pairs_generator=None, time_bin=1., average=True):
        """
        Function to generate an array of cross correlations computed
        between pairs of cells within the SpikeTrains.

        Inputs:
            nb_pairs        - int specifying the number of pairs
            pairs_generator - The generator that will be used to draw the pairs. If None, a default one is
                              created as RandomPairs(spk, spk, no_silent=False, no_auto=True)
            time_bin        - The time bin used to gather the spikes
            average         - If true, only the averaged CC among all the pairs is returned (less memory needed)

        Examples
            >> a.pairwise_cc(500, time_bin=1, averagec=True)
            >> a.pairwise_cc(100, CustomPairs(a,a,[(i,i+1) for i in xrange(100)]), time_bin=5)

        See also
            pairwise_pearson_corrcoeff, pairwise_cc_zero, RandomPairs, AutoPairs, CustomPairs
        """
        # We have to extract only the non silent cells, to avoid problems
        if pairs_generator is None:
            pairs_generator = RandomPairs(self, self, True, True)

        # Then we select the pairs of cells
        pairs = pairs_generator.get_pairs(nb_pairs)
        N = len(pairs)
        length = 2 * (len(pairs_generator.spk1.time_axis(time_bin)) - 1)
        if not average:
            results = np.zeros((N, length), float)
        else:
            results = np.zeros(length, float)
        for idx in range(N):
            # We need to avoid empty spike histogram, otherwise the ccf function
            # will give a nan vector
            hist_1 = pairs_generator.spk1[pairs[idx, 0]].time_histogram(time_bin)
            hist_2 = pairs_generator.spk2[pairs[idx, 1]].time_histogram(time_bin)
            if not average:
                results[idx, :] = ccf(hist_1, hist_2)
            else:
                results += ccf(hist_1, hist_2)
        if not average:
            return results
        else:
            return results / N

    def pairwise_cc_zero(self, nb_pairs, pairs_generator=None, time_bin=1., time_window=None):
        """
        Function to return the normalized cross correlation coefficient at zero time
        lag according to the method given in:
        See A. Aertsen et al,
            Dynamics of neuronal firing correlation: modulation of effective connectivity
            J Neurophysiol, 61:900-917, 1989

        The coefficient is averaged over N pairs of cells. If time window is specified, compute
        the corr coeff on a sliding window, and therefore returns not a value but a vector.

        Inputs:
            nb_pairs        - int specifying the number of pairs
            pairs_generator - The generator that will be used to draw the pairs. If None, a default one is
                              created as RandomPairs(spk, spk, no_silent=False, no_auto=True)
            time_bin        - The time bin used to gather the spikes
            time_window     - None by default, and then a single number, the normalized CC is returned.
                              If this is a float, then size (in ms) of the sliding window used to
                              compute the normalized cc. A Vector is then returned
        Examples:
            >> a.pairwise_cc_zero(100, time_bin=1)
                1.0
            >> a.pairwise_cc_zero(100, CustomPairs(a, a, [(i,i+1) for i in xrange(100)]), time_bin=1)
                0.45
            >> a.pairwise_cc_zero(100, RandomPairs(a, a, no_silent=True), time_bin=5, time_window=10)

        See also:
            pairwise_cc, pairwise_pearson_corrcoeff, RandomPairs, AutoPairs, CustomPairs
        """
        if pairs_generator is None:
            pairs_generator = RandomPairs(self, self, False, True)

        spk1, spk2, pairs = self.__select_with_pairs__(nb_pairs, pairs_generator)
        N = len(pairs)

        if spk1.time_parameters() != spk2.time_parameters():
            raise Exception("The two SpikeList must have common time axis !")

        num_bins = int(np.round((self.t_stop - self.t_start) / time_bin) + 1)
        mat_neur1 = np.zeros((num_bins, N), int)
        mat_neur2 = np.zeros((num_bins, N), int)
        times1, ids1 = spk1.convert("times, ids")
        times2, ids2 = spk2.convert("times, ids")

        cells_id = spk1.id_list
        for idx in range(len(cells_id)):
            ids1[np.where(ids1 == cells_id[idx])[0]] = idx
        cells_id = spk2.id_list
        for idx in range(len(cells_id)):
            ids2[np.where(ids2 == cells_id[idx])[0]] = idx
        times1 = np.array(((times1 - self.t_start) / time_bin), int)
        times2 = np.array(((times2 - self.t_start) / time_bin), int)
        mat_neur1[times1, ids1] = 1
        mat_neur2[times2, ids2] = 1
        if time_window:
            nb_pts = int(time_window / time_bin)
            mat_prod = mat_neur1 * mat_neur2
            cc_time = np.zeros((num_bins - nb_pts), float)
            xaxis = np.zeros((num_bins - nb_pts))
            M = float(nb_pts * N)
            bound = int(np.ceil(nb_pts / 2))
            for idx in range(bound, num_bins - bound):
                s_min = idx - bound
                s_max = idx + bound
                Z = np.sum(np.sum(mat_prod[s_min:s_max])) / M
                X = np.sum(np.sum(mat_neur1[s_min:s_max])) / M
                Y = np.sum(np.sum(mat_neur2[s_min:s_max])) / M
                cc_time[s_min] = (Z - X * Y) / np.sqrt((X * (1 - X)) * (Y * (1 - Y)))
                xaxis[s_min] = time_bin * idx
            return cc_time
        else:
            M = float(num_bins * N)
            X = len(times1) / M
            Y = len(times2) / M
            Z = np.sum(np.sum(mat_neur1 * mat_neur2)) / M
            return (Z - X * Y) / np.sqrt((X * (1 - X)) * (Y * (1 - Y)))

    def distance_victorpurpura(self, nb_pairs, pairs_generator=None, cost=0.5):
        """
        Function to calculate the Victor-Purpura distance averaged over N pairs in the SpikeList
        See J. D. Victor and K. P. Purpura,
            Nature and precision of temporal coding in visual cortex: a metric-space
            analysis.,
            J Neurophysiol,76(2):1310-1326, 1996

        Inputs:
            nb_pairs        - int specifying the number of pairs
            pairs_generator - The generator that will be used to draw the pairs. If None, a default one is
                              created as RandomPairs(spk, spk, no_silent=False, no_auto=True)
            cost            - The cost parameter. See the paper for more informations. BY default, set to 0.5

        See also
            RandomPairs, AutoPairs, CustomPairs
        """
        if pairs_generator is None:
            pairs_generator = RandomPairs(self, self, False, True)

        pairs = pairs_generator.get_pairs(nb_pairs)
        N = len(pairs)
        distance = 0.
        for idx in range(N):
            idx_1 = pairs[idx, 0]
            idx_2 = pairs[idx, 1]
            distance += pairs_generator.spk1[idx_1].distance_victorpurpura(pairs_generator.spk2[idx_2], cost)
        return distance / N

    def distance_kreuz(self, nb_pairs, pairs_generator=None, dt=0.1):
        """
        Function to calculate the Kreuz/Politi distance between two spike trains
        See Kreuz, T.; Haas, J.S.; Morelli, A.; Abarbanel, H.D.I. & Politi,
        A. Measuring spike train synchrony.
        J Neurosci Methods, 2007, 165, 151-161

        Inputs:
            nb_pairs        - int specifying the number of pairs
            pairs_generator - The generator that will be used to draw the pairs. If None, a default one is
                              created as RandomPairs(spk, spk, no_silent=False, no_auto=True)
            dt              - The time bin used to discretized the spike times

        See also
            RandomPairs, AutoPairs, CustomPairs
        """
        if pairs_generator is None:
            pairs_generator = RandomPairs(self, self, False, True)

        pairs = pairs_generator.get_pairs(nb_pairs)
        N = len(pairs)

        distance = 0.
        for idx in range(N):
            idx_1 = pairs[idx, 0]
            idx_2 = pairs[idx, 1]
            distance += pairs_generator.spk1[idx_1].distance_kreuz(pairs_generator.spk2[idx_2], dt)
        return distance/N

    def mean_rate_variance(self, time_bin):
        """
        Return the standard deviation of the firing rate along time,
        if events are binned with a time bin.

        Inputs:
            time_bin - time bin to bin events

        See also
            mean_rate, mean_rates, mean_rate_covariance, firing_rate
        """
        firing_rate = self.firing_rate(time_bin)
        return np.var(np.mean(firing_rate, axis=0))

    def mean_rate_covariance(self, spikelist, time_bin):
        """
        Return the covariance of the firing rate along time,
        if events are binned with a time bin.

        Inputs:
            spikelist - the other spikelist to compute covariance
            time_bin  - time bin to bin events

        See also
            mean_rate, mean_rates, mean_rate_variance, firing_rate
        """
        if not isinstance(spikelist, SpikeList):
            raise Exception("Error, argument should be a SpikeList object")
        if not spikelist.time_parameters() == self.time_parameters():
            raise Exception("Error, both SpikeLists should share common t_start, t_stop")
        frate_1 = self.firing_rate(time_bin, average=True)
        frate_2 = spikelist.firing_rate(time_bin, average=True)
        N = len(frate_1)
        cov = np.sum(frate_1 * frate_2) / N - np.sum(frate_1) * np.sum(frate_2) / (N * N)
        return cov

    def psth(self, events, average=True, time_bin=2, t_min=50, t_max=50):
        """
        Return the psth of the cells contained in the SpikeList according to selected events,
        on a time window t_spikes - tmin, t_spikes + tmax
        Can return either the averaged psth (average = True), or an array of all the
        psth triggered by all the spikes.

        Inputs:
            events  - Can be a SpikeTrain object (and events will be the spikes) or just a list
                      of times
            average - If True, return a single vector of the averaged waveform. If False,
                      return an array of all the waveforms.
            time_bin- The time bin (in ms) used to gather the spike for the psth
            t_min   - Time (>0) to average the signal before an event, in ms (default 0)
            t_max   - Time (>0) to average the signal after an event, in ms  (default 100)

        Examples:
            >> vm.psth(spktrain, average=False, t_min = 50, t_max = 150)
            >> vm.psth(spktrain, average=True)
            >> vm.psth(range(0,1000,10), average=False)

        See also
            SpikeTrain.spike_histogram
        """

        if isinstance(events, SpikeTrain):
            events = events.spike_times
        assert (t_min >= 0) and (t_max >= 0), "t_min and t_max should be greater than 0"
        assert len(events) > 0, "events should not be empty and should contained at least one element"

        spk_hist = self.spike_histogram(time_bin)
        count = 0
        t_min_l = np.floor(t_min / time_bin)
        t_max_l = np.floor(t_max / time_bin)
        result = np.zeros((len(self), t_min_l + t_max_l), np.float32)
        t_start = np.floor(self.t_start / time_bin)
        t_stop = np.floor(self.t_stop / time_bin)

        for ev in events:
            ev = np.floor(ev / time_bin)
            if ((ev - t_min_l) > t_start) and (ev + t_max_l) < t_stop:
                count += 1
                result += spk_hist[:, (ev - t_start - t_min_l):ev - t_start + t_max_l]
        result /= count
        if average:
            result = np.mean(result, 0)
        return result

    def pairwise_pearson_corrcoeff(self, nb_pairs, pairs_generator=None, time_bin=1., all_coef=False):
        """
        Function to return the mean and the variance of the pearson correlation coefficient.
        For more details, see Kumar et al, ....

        Inputs:
            nb_pairs        - int specifying the number of pairs
            pairs_generator - The generator that will be used to draw the pairs. If None, a default one is
                              created as RandomPairs(spk, spk, no_silent=False, no_auto=True)
            time_bin        - The time bin used to gather the spikes
            all_coef        - If True, the whole list of correlation coefficient is returned

        Examples
            >> spk.pairwise_pearson_corrcoeff(50, time_bin=5)
                (0.234, 0.0087)
            >> spk.pairwise_pearson_corrcoeff(100, AutoPairs(spk, spk))
                (1.0, 0.0)

        See also
            pairwise_cc, pairwise_cc_zero, RandomPairs, AutoPairs, CustomPairs
        """
        # We have to extract only the non silent cells, to avoid problems
        if pairs_generator is None:
            pairs_generator = RandomPairs(self, self, True, True)

        pairs = pairs_generator.get_pairs(nb_pairs)
        N = len(pairs)
        cor = np.zeros(N, float)

        for idx in range(N):
            # get spike counts at the specified bin size
            hist_1 = pairs_generator.spk1[pairs[idx, 0]].time_histogram(time_bin)
            hist_2 = pairs_generator.spk2[pairs[idx, 1]].time_histogram(time_bin)

            # count covariance
            cov = np.corrcoef(hist_1, hist_2)[1][0]
            cor[idx] = cov
        if all_coef:
            return cor
        else:
            return cor.mean(), cor.std()

    def spike_counts(self, dt, normalized=False, binary=False):
        """
        Returns array with all single neuron spike counts
        :param dt:
        :param normalized:
        :param binary:
        :return:
        """
        counts = [self.spiketrains[v].time_histogram(time_bin=dt, normalized=normalized, binary=binary) for v in
                  self.id_list]
        return np.array(counts)

    def convert(self, format="[times, ids]", relative=False, quantized=False):
        """
        Return a new representation of the SpikeList object, in a user designed format.
            format is an expression containing either the keywords times and ids,
            time and id.

        Inputs:
            relative -  a boolean to say if a relative representation of the spikes
                        times compared to t_start is needed
            quantized - a boolean to round the spikes_times.

        Examples:
            >> spk.convert("[times, ids]") will return a list of two elements, the
                first one being the array of all the spikes, the second the array of all the
                corresponding ids
            >> spk.convert("[(time,id)]") will return a list of tuples (time, id)

        See also
            SpikeTrain.format
        """
        is_times = re.compile("times")
        is_ids = re.compile("ids")
        if len(self) > 0:
            times = np.concatenate([st.format(relative, quantized) for st in self.spiketrains.values()])
            ids = np.concatenate([id * np.ones(len(st.spike_times), int) for id, st in self.spiketrains.items()])
        else:
            times = []
            ids   = []
        if is_times.search(format):
            if is_ids.search(format):
                return eval(format)
            else:
                raise Exception("You must have a format with [times, ids] or [time, id]")
        is_times = re.compile("time")
        is_ids = re.compile("id")
        if is_times.search(format):
            if is_ids.search(format):
                result = []
                for id, time in zip(ids, times):
                    result.append(eval(format))
            else:
                raise Exception("You must have a format with [times, ids] or [time, id]")
            return result

    def raw_data(self):
        """
        Function to return a N by 2 array of all times and ids.

        Examples:
            >> spklist.raw_data()
            >> array([[  1.00000000e+00,   1.00000000e+00],
                      [  1.00000000e+00,   1.00000000e+00],
                      [  2.00000000e+00,   2.00000000e+00],
                         ...,
                      [  2.71530000e+03,   2.76210000e+03]])

        See also:
            convert()
        """
        data = np.array(self.convert("[times, ids]"), np.float32)
        data = np.transpose(data)
        return data

    def raster_plot(self, with_rate=False, ax=None, dt=1.0, display=True, save=False, **kwargs):
        """
        Plot a simple raster, for a quick check
        """
        if ax is None:
            fig = pl.figure()
            if with_rate:
                ax1 = pl.subplot2grid((30, 1), (0, 0), rowspan=23, colspan=1)
                ax2 = pl.subplot2grid((30, 1), (24, 0), rowspan=5, colspan=1, sharex=ax1)
                ax2.set(xlabel='Time [ms]', ylabel='Rate')
                ax1.set(ylabel='Neuron')
            else:
                ax1 = fig.add_subplot(111)
        else:
            if with_rate:
                assert isinstance(ax, list), "Incompatible properties... (with_rate requires two axes provided or " \
                                             "None)"
                ax1 = ax[0]
                ax2 = ax[1]
            else:
                ax1 = ax

        ax1.plot(self.raw_data()[:, 0], self.raw_data()[:, 1], '.', **kwargs)

        if with_rate:
            time = self.time_axis(dt)[:-1]
            rate = self.firing_rate(dt, average=True)
            ax2.plot(time, rate, **kwargs)
        ax1.set(ylim=[min(self.id_list), max(self.id_list)], xlim=[self.t_start, self.t_stop])
        ax2 = None
        if save:
            assert isinstance(save, str), "Please provide filename"
            pl.savefig(save)

        if display:
            pl.show()

        return fig, (ax1, ax2)


############################################################################################
class PairsGenerator(object):
    """
    PairsGenerator(SpikeList, SpikeList, no_silent)
    This class defines the concept of PairsGenerator, that will be used by all
    the functions using pairs of cells. Functions get_pairs() will then be used
    to obtain pairs from the generator.
    Inputs:
        spk1      - First SpikeList object to take cells from
        spk2      - Second SpikeList object to take cells from
        no_silent - Boolean to say if only non silent cells should
                    be considered. False by default
    Examples:
        >> p = PairsGenerator(spk1, spk1, True)
        >> p.get_pairs(100)
    See also AutoPairs, RandomPairs, CustomPairs, DistantDependentPairs
    """
    def __init__(self, spk1, spk2, no_silent=False):
        self.spk1 = spk1
        self.spk2 = spk2
        self.no_silent = no_silent
        self._get_id_lists()

    def _get_id_lists(self):
        self.ids_1 = set(self.spk1.id_list)
        self.ids_2 = set(self.spk2.id_list)
        if self.no_silent:
            n1 = set(self.spk1.select_ids("len(cell.spike_times) == 0"))
            n2 = set(self.spk2.select_ids("len(cell.spike_times) == 0"))
            self.ids_1 -= n1
            self.ids_2 -= n2


########################################################################################################################
class RandomPairs(PairsGenerator):
    """
    RandomPairs(SpikeList, SpikeList, no_silent, no_auto). Inherits from PairsGenerator.
    Generator that will return random pairs of elements.
    Inputs:
        spk1      - First SpikeList object to take cells from
        spk2      - Second SpikeList object to take cells from
        no_silent - Boolean to say if only non silent cells should
                    be considered. True by default
        no_auto   - Boolean to say if pairs with the same element (id,id) should
                    be removed. True by default, i.e those pairs are discarded
    Examples:
        >> p = RandomPairs(spk1, spk1, True, False)
        >> p.get_pairs(4)
            [[1,3],[2,5],[1,4],[5,5]]
        >> p = RandomPairs(spk1, spk1, True, True)
        >> p.get_pairs(3)
            [[1,3],[2,5],[1,4]]
    See also RandomPairs, CustomPairs, DistantDependentPairs
    """
    def __init__(self, spk1, spk2, no_silent=True, no_auto=True):
        PairsGenerator.__init__(self, spk1, spk2, no_silent)
        self.no_auto = no_auto

    def get_pairs(self, nb_pairs):
        cells1 = np.array(list(self.ids_1), int)
        cells2 = np.array(list(self.ids_2), int)
        pairs = np.zeros((0, 2), int)
        N1 = len(cells1)
        N2 = len(cells2)
        T = min(N1, N2)
        while len(pairs) < nb_pairs:
            N = min(nb_pairs - len(pairs), T)
            tmp_pairs = np.zeros((N, 2), int)
            tmp_pairs[:, 0] = cells1[np.floor(np.random.uniform(0, N1, N)).astype(int)]
            tmp_pairs[:, 1] = cells2[np.floor(np.random.uniform(0, N2, N)).astype(int)]
            if self.no_auto:
                idx = np.where(tmp_pairs[:, 0] == tmp_pairs[:, 1])[0]
                pairs = np.concatenate((pairs, np.delete(tmp_pairs, idx, axis=0)))
            else:
                pairs = np.concatenate((pairs, tmp_pairs))
        return pairs