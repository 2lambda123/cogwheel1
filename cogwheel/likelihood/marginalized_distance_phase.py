"""
Provide class ``MarginalizedDistancePhaseLikelihood`` to sample using a
likelihood marginalized over distance and phase.
"""
import numpy as np
from scipy.special import logsumexp
from .marginalized_distance import MarginalizedDistanceLikelihood
import itertools

class MarginalizedDistancePhaseLikelihood(MarginalizedDistanceLikelihood):
    
    """
    Modified `MarginalizedDistanceLikelihood` marginalize with a 
    grid over phases. Thus, it removes two dimension from the parameter 
    space.
    """

    def __init__(self, lookup_table, event_data, waveform_generator,
                 par_dic_0, fbin=None, pn_phase_tol=None,
                 spline_degree=3, n_phi=100):
    
        """
        Parameters
        ----------
        event_data: Instance of `data.EventData`
        waveform_generator: Instance of `waveform.WaveformGenerator`.
        par_dic_0: dictionary with parameters of the reference waveform,
                   should be close to the maximum likelihood waveform.
        fbin: Array with edges of the frequency bins used for relative
              binning [Hz]. Alternatively, pass `pn_phase_tol`.
        pn_phase_tol: Tolerance in the post-Newtonian phase [rad] used
                      for defining frequency bins. Alternatively, pass
                      `fbin`.
        spline_degree: int, degree of the spline used to interpolate the
                        ratio between waveform and reference waveform for
                       relative binning.
        lookup_table: Instance of ``likelihood.LookupTable`` to compute
                      the marginalized likelihood.
        n_phi : number of equally spaced phi_ref grid points, in the 
                (0, 2*pi) interval.
        """
        
        super().__init__(lookup_table, event_data, waveform_generator,
                 par_dic_0, fbin, pn_phase_tol, spline_degree)

        self.n_phi = n_phi
        self.m_arr = np.fromiter(waveform_generator._harmonic_modes_by_m, int)
        self.m_inds, self.mprime_inds = zip(
            *itertools.combinations_with_replacement(
            range(len(self.m_arr)), 2))
        
        self.phi = np.linspace(0, 2*np.pi, n_phi, endpoint=False)
        self._dh_phasor = np.exp(-1j * np.outer(self.m_arr, self.phi))
        self._hh_phasor = np.exp(1j * np.outer(self.m_arr[self.m_inds,] 
                                               - self.m_arr[self.mprime_inds,],
                                               self.phi))

    @property
    def params(self):
        """
        Parameters expected in `par_dic` for likelihood evaluations.
        """
        return sorted(set(self.waveform_generator.params) 
                      - {'d_luminosity','phi_ref'})
    
    def _get_dh_hh_on_phi_grid(self, par_dic):
        dh_mpd, hh_mpPd = \
            self._get_dh_hh_complex_no_asd_drift(par_dic | {'phi_ref': 0.0})
        dh_o = np.einsum('mpd, mo, d -> o', 
                         dh_mpd, self._dh_phasor, self.asd_drift**-2).real
        hh_o = np.einsum('mpPd, mo, d-> o', 
                         hh_mpPd, self._hh_phasor, self.asd_drift**-2).real
        return dh_o, hh_o
    
    def _lnlike_dist_marg_on_phi_grid(self, par_dic):
        """
        Return log likelihood, marginalized over distance and phase, 
        using relative binning.
        """
        dh_o, hh_o = \
            self._get_dh_hh_on_phi_grid(
            par_dic | {'phi_ref': 0.0, 
                       'd_luminosity': self.lookup_table.REFERENCE_DISTANCE})
        
        return self.lookup_table.lnlike_marginalized(dh_o, hh_o)
                
    def lnlike(self, par_dic):
        return (logsumexp(self._lnlike_dist_marg_on_phi_grid(par_dic))
                - np.log(self.n_phi))

    def lnlike_no_phase_marginalization(self, par_dic):
        """
        Return log likelihood, marginalized over distance, using
        relative binning.
        """
        return super().lnlike(par_dic)

    def lnlike_no_marginalization(self, par_dic):
        """
        Return log likelihood, not marginalized over distance or phase, 
        using relative binning.
        """
        return super().lnlike_no_marginalization(par_dic)

    
    def postprocess_samples(self, samples, force_update=True):
        """
        Add columns 'd_luminosity' and 'phi_ref' to a DataFrame of 
        samples, with values taken randomly from the conditional
        posterior. `samples` needs to have columns for all 
        `self.params`.

        Parameters
        ----------
        samples: Dataframe with sampled params
        force_update: bool, whether to force an update if the luminosity
                      distance samples already exist.
        """

        @np.vectorize
        def sample_phase(**par_dic):
            lnl_o = self._lnlike_dist_marg_on_phi_grid(par_dic)
            p_o = np.exp(lnl_o - lnl_o.max())
            phase_cumulative = np.cumsum(p_o)/np.sum(p_o)
            u_phi= np.random.uniform(0, 1)
            phi_ref = np.interp(u_phi, phase_cumulative, self.phi)
            return phi_ref
        
        
        @np.vectorize
        def sample_distance(**par_dic):
            dh_hh = self._get_dh_hh_no_asd_drift(
                par_dic
                | {'d_luminosity': self.lookup_table.REFERENCE_DISTANCE})
            d_h, h_h = np.matmul(dh_hh, self.asd_drift**-2)
            return self.lookup_table.sample_distance(d_h, h_h)
        
        samples['phi_ref'] = sample_phase(**samples[self.params])
        samples['d_luminosity'] = sample_distance(
            **samples[self.params + ['phi_ref']])    