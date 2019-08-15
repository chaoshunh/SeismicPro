"""File contains seismic dataset."""
import numpy as np
from scipy.optimize import minimize
from tdigest import TDigest

from ..batchflow import Dataset
from ..src.seismic_index import FieldIndex
from ..src.seismic_batch import SeismicBatch


class SeismicDataset(Dataset):
    """Dataset for seismic data."""

    def __init__(self, index, batch_class=SeismicBatch, preloaded=None, *args, **kwargs):
        super().__init__(index, batch_class=batch_class, preloaded=preloaded, *args, **kwargs)

    def find_sdc_params(self, component, speed, loss, indices=None, time=None, initial_point=None,
                        method='Powell', bounds=None, tslice=None, **kwargs):
        """ Finding an optimal parameters for correction of spherical divergence.

        Parameters
        ----------
        component : str
            Component with fields.
        speed : array
            Wave propagation speed depending on the depth.
            Speed is measured in milliseconds.
        loss : callable
            Function to minimize.
        indices : array-like, optonal
            Which items from dataset to use in parameter estimation.
            If `None`, defaults to first element of dataset.
        time : array, optional
           Trace time values. If `None` defaults to self.meta[src]['samples'].
           Time measured in either in samples or in milliseconds.
        initial_point : array of 2
            Started values for $v_{pow}$ and $t_{pow}$.
            If None defaults to $v_{pow}=2$ and $t_{pow}=1$.
        method : str, optional, default ```Powell```
            Minimization method, see ```scipy.optimize.minimize```.
        bounds : sequence, optional
            Sequence of (min, max) optimization bounds for each parameter.
            If `None` defaults to ((0, 5), (0, 5)).
        tslice : slice, optional
            Lenght of loaded field.

        Returns
        -------
            : array
            Coefficients for speed and time.

        Note
        ----
        To save parameters as SeismicDataset attribute use ```save_to=D('attr_name')``` (works only
        in pipeline).
        If you want to save parameters to pipeline variable use save_to argument with following
        syntax: ```save_to=V('variable_name')```.
        """
        if not isinstance(self.index, FieldIndex):
            raise ValueError("Index must be FieldIndex, not {}".format(type(self.index)))

        if indices is None:
            indices = self.indices[:1]

        batch = self.create_batch(indices).load(components=component, fmt='segy', tslice=tslice)
        field = getattr(batch, component)[0]
        samples = batch.meta[component]['samples']

        bounds = ((0, 5), (0, 5)) if bounds is None else bounds
        initial_point = (2, 1) if initial_point is None else initial_point

        time = samples if time is None else np.array(time, dtype=int)
        step = np.diff(time[:2])[0].astype(int)
        speed = np.array(speed, dtype=int)[::step]
        args = field, time, speed

        func = minimize(loss, initial_point, args=args, method=method, bounds=bounds, **kwargs)
        return func.x

    def find_equalization_params(self, batch, component, record_id='fnum', sample_size=10000,
                                 container_name='equal_params', **kwargs):
        """ Calculate parameters for dataset equalization.
        """
        if not isinstance(self.index, FieldIndex):
            raise ValueError("Index must be FieldIndex, not {}".format(type(self.index)))

        private_name = '_' + container_name
        params = getattr(self, private_name, None)
        if params is None:
            records = np.unique(self.index._idf[record_id])
            delta, K = kwargs.pop('delta', 0.01), kwargs.pop('K', 25)
            params = dict(zip(records, [TDigest(delta, K) for _ in records]))
            params['record_id'] = record_id
            setattr(self, private_name, params)

        for idx in batch.indices:
            record = np.unique(batch.index._idf.loc[idx, record_id])
            if len(record) == 1:
                record = record[0]
            else:
                raise ValueError('Field {} contains more than one record!'.format(batch.index.indices[0]))

            pos = batch.index.get_pos(idx)
            sample = np.random.choice(getattr(batch, component)[pos].reshape(-1), size=sample_size)

            params[record].batch_update(sample)

        statistics = dict([record, (digest.percentile(5), digest.percentile(95))] for record, digest in params.items())
        setattr(self, container_name, statistics)
