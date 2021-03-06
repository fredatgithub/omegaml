from __future__ import absolute_import

import os
from unittest import TestCase, skipUnless

from sklearn.datasets import make_classification
from sklearn.exceptions import NotFittedError
from sklearn.linear_model import LogisticRegression
from sklearn.linear_model.base import LinearRegression
from sklearn.linear_model.stochastic_gradient import SGDRegressor
from sklearn.metrics.regression import mean_squared_error
from sklearn.model_selection import GridSearchCV
from sklearn.pipeline import Pipeline
from sklearn.utils.validation import DataConversionWarning

import numpy as np
from omegaml import Omega
from omegaml.util import delete_database, reshaped, settings
import pandas as pd
from six.moves import range


class RuntimeTests(TestCase):

    def setUp(self):
        TestCase.setUp(self)
        delete_database()

    def tearDown(self):
        TestCase.tearDown(self)

    def test_predict(self):
        # create some data
        x = np.array(list(range(0, 10)))
        y = x * 2
        df = pd.DataFrame({'x': x,
                           'y': y})
        X = df[['x']]
        Y = df[['y']]
        # put into Omega
        os.environ['DJANGO_SETTINGS_MODULE'] = ''
        om = Omega()
        om.runtime.celeryapp.conf.CELERY_ALWAYS_EAGER = True
        om.datasets.put(X, 'datax')
        om.datasets.put(Y, 'datay')
        om.datasets.get('datax')
        om.datasets.get('datay')
        # create a model locally, fit it, store in Omega
        lr = LinearRegression()
        lr.fit(X, Y)
        pred = lr.predict(X)
        om.models.put(lr, 'mymodel')
        self.assertIn('mymodel', om.models.list('*'))
        # have Omega predict it
        # -- using data already in Omega
        result = om.runtime.model('mymodel').predict('datax')
        pred1 = result.get()
        # -- using data provided locally
        #    note this is the same as
        #        om.datasets.put(X, 'foo')
        #        om.runtimes.model('mymodel').predict('foo')
        result = om.runtime.model('mymodel').predict(X)
        pred2 = result.get()
        self.assertTrue(
            (pred == pred1).all(), "runtimes prediction is different(1)")
        self.assertTrue(
            (pred == pred2).all(), "runtimes prediction is different(2)")

    def test_fit(self):
        # create some data
        x = np.array(list(range(0, 10)))
        y = x * 2
        df = pd.DataFrame({'x': x,
                           'y': y})
        X = df[['x']]
        Y = df[['y']]
        # put into Omega
        os.environ['DJANGO_SETTINGS_MODULE'] = ''
        om = Omega()
        om.runtime.celeryapp.conf.CELERY_ALWAYS_EAGER = True
        om.datasets.put(X, 'datax')
        om.datasets.put(Y, 'datay')
        om.datasets.get('datax')
        om.datasets.get('datay')
        # create a model locally, store (unfitted) in Omega
        lr = LinearRegression()
        om.models.put(lr, 'mymodel2')
        self.assertIn('mymodel2', om.models.list('*'))
        # predict locally for comparison
        lr.fit(X, Y)
        pred = lr.predict(X)
        # try predicting without fitting
        with self.assertRaises(NotFittedError):
            result = om.runtime.model('mymodel2').predict('datax')
            result.get()
        # have Omega fit the model then predict
        result = om.runtime.model('mymodel2').fit('datax', 'datay')
        result.get()
        # check the new model version metadata includes the datax/y references
        meta = om.models.metadata('mymodel2')
        self.assertIn('metaX', meta.attributes)
        self.assertIn('metaY', meta.attributes)
        # -- using data already in Omega
        result = om.runtime.model('mymodel2').predict('datax')
        pred1 = result.get()
        # -- using data provided locally
        #    note this is the same as
        #        om.datasets.put(X, 'foo')
        #        om.runtimes.model('mymodel2').predict('foo')
        result = om.runtime.model('mymodel2').fit(X, Y)
        result = om.runtime.model('mymodel2').predict(X)
        pred2 = result.get()
        # -- check the local data provided to fit was stored as intended
        meta = om.models.metadata('mymodel2')
        self.assertIn('metaX', meta.attributes)
        self.assertIn('metaY', meta.attributes)
        self.assertIn('_fitX', meta.attributes.get('metaX').get('collection'))
        self.assertIn('_fitY', meta.attributes.get('metaY').get('collection'))
        self.assertTrue(
            (pred == pred1).all(), "runtimes prediction is different(1)")
        self.assertTrue(
            (pred == pred2).all(), "runtimes prediction is different(2)")

    def test_partial_fit(self):
        # create some data
        x = np.array(list(range(0, 10)))
        y = x * 2
        df = pd.DataFrame({'x': x,
                           'y': y})
        X = df[['x']][0:2]
        Y = df[['y']][0:2]
        # put into Omega
        os.environ['DJANGO_SETTINGS_MODULE'] = ''
        om = Omega()
        om.runtime.celeryapp.conf.CELERY_ALWAYS_EAGER = True
        om.datasets.put(df[['x']], 'datax-full')
        om.datasets.put(X, 'datax')
        om.datasets.put(Y, 'datay')
        om.datasets.get('datax')
        om.datasets.get('datay')
        # create a model locally, store (unfitted) in Omega
        # -- ignore warnings on y shape
        import warnings
        warnings.filterwarnings("ignore", category=DataConversionWarning)
        lr = SGDRegressor(max_iter=1000, tol=1e-3)
        om.models.put(lr, 'mymodel2')
        # have Omega fit the model to get a start, then predict
        result = om.runtime.model('mymodel2').fit('datax', 'datay')
        result.get()
        # check the new model version metadata includes the datax/y references
        result = om.runtime.model('mymodel2').predict('datax-full')
        pred1 = result.get()
        mse = mean_squared_error(df.y, pred1)
        self.assertGreater(mse, 40)
        # fit mini batches add better training data, update model
        batch_size = 2
        for i, start in enumerate(range(0, len(df))):
            previous_mse = mse
            X = df[['x']][start:start + batch_size]
            Y = df[['y']][start:start + batch_size]
            om.datasets.put(X, 'datax-update', append=False)
            om.datasets.put(Y, 'datay-update', append=False)
            result = om.runtime.model('mymodel2').partial_fit(
                'datax-update', 'datay-update')
            result.get()
            # check the new model version metadata includes the datax/y
            # references
            result = om.runtime.model('mymodel2').predict('datax-full')
            pred1 = result.get()
            mse = mean_squared_error(df.y, pred1)
            self.assertLess(mse, previous_mse)

    def test_predict_pure_python(self):
        # create some data
        x = np.array(list(range(0, 10)))
        y = x * 2
        df = pd.DataFrame({'x': x,
                           'y': y}).astype('O')
        X = [[x] for x in list(df.x)]
        Y = [[y] for y in list(df.y)]
        # put into Omega -- assume a client with pandas, scikit learn
        os.environ['DJANGO_SETTINGS_MODULE'] = ''
        om = Omega()
        om.runtime.pure_python = True
        om.runtime.celeryapp.conf.CELERY_ALWAYS_EAGER = True
        om.datasets.put(X, 'datax')
        om.datasets.put(Y, 'datay')
        Xhat = om.datasets.get('datax')
        Yhat = om.datasets.get('datay')
        self.assertEqual([X], Xhat)
        self.assertEqual([Y], Yhat)
        # have Omega fit the model then predict
        lr = LinearRegression()
        lr.fit(X, Y)
        pred = lr.predict(X)
        om.models.put(lr, 'mymodel2')
        # -- using data provided locally
        #    note this is the same as
        #        om.datasets.put(X, 'foo')
        #        om.runtimes.model('mymodel2').predict('foo')
        result = om.runtime.model('mymodel2').predict(reshaped(X))
        pred2 = result.get()
        self.assertTrue(
            (pred == pred2).all(), "runtimes prediction is different(1)")
        self.assertTrue(
            (pred == pred2).all(), "runtimes prediction is different(2)")

    def test_predict_hdf_dataframe(self):
        # create some data
        x = np.array(list(range(0, 10)))
        y = x * 2
        df = pd.DataFrame({'x': x,
                           'y': y})
        X = df['x']
        Y = df['y']
        # put into Omega -- assume a client with pandas, scikit learn
        os.environ['DJANGO_SETTINGS_MODULE'] = ''
        om = Omega()
        om.runtime.pure_python = True
        om.runtime.celeryapp.conf.CELERY_ALWAYS_EAGER = True
        om.datasets.put(X, 'datax', as_hdf=True)
        om.datasets.put(Y, 'datay', as_hdf=True)
        # have Omega fit the model then predict
        lr = LinearRegression()
        lr.fit(reshaped(X), reshaped(Y))
        pred = lr.predict(reshaped(X))
        om.models.put(lr, 'mymodel2')
        # -- using data provided locally
        #    note this is the same as
        #        om.datasets.put(X, 'foo')
        #        om.runtimes.model('mymodel2').predict('foo')
        result = om.runtime.model('mymodel2').predict('datax')
        pred2 = result.get()
        self.assertTrue(
            (pred == pred2).all(), "runtimes prediction is different(1)")
        self.assertTrue(
            (pred == pred2).all(), "runtimes prediction is different(2)")

    def test_fit_pipeline(self):
        # create some data
        x = np.array(list(range(0, 10)))
        y = x * 2
        df = pd.DataFrame({'x': x,
                           'y': y})
        X = df[['x']]
        Y = df[['y']]
        # put into Omega
        os.environ['DJANGO_SETTINGS_MODULE'] = ''
        om = Omega()
        om.runtime.celeryapp.conf.CELERY_ALWAYS_EAGER = True
        om.datasets.put(X, 'datax')
        om.datasets.put(Y, 'datay')
        om.datasets.get('datax')
        om.datasets.get('datay')
        # create a pipeline locally, store (unfitted) in Omega
        p = Pipeline([
            ('lr', LinearRegression()),
        ])
        om.models.put(p, 'mymodel2')
        self.assertIn('mymodel2', om.models.list('*'))
        # predict locally for comparison
        p.fit(reshaped(X), reshaped(Y))
        pred = p.predict(reshaped(X))
        # have Omega fit the model then predict
        result = om.runtime.model('mymodel2').fit('datax', 'datay')
        result.get()
        result = om.runtime.model('mymodel2').predict('datax')
        pred1 = result.get()
        self.assertTrue(
            (pred == pred1).all(), "runtimes prediction is different(1)")

    def test_score(self):
        # create some data
        x = np.array(list(range(0, 10)))
        y = x * 2
        df = pd.DataFrame({'x': x,
                           'y': y})
        X = df[['x']]
        Y = df[['y']]
        # put into Omega
        os.environ['DJANGO_SETTINGS_MODULE'] = ''
        om = Omega()
        om.runtime.celeryapp.conf.CELERY_ALWAYS_EAGER = True
        om.datasets.put(X, 'datax')
        om.datasets.put(Y, 'datay')
        om.datasets.get('datax')
        om.datasets.get('datay')
        # create a model locally, fit it, store in Omega
        lr = LinearRegression()
        lr.fit(X, Y)
        scores = lr.score(X, Y)
        om.models.put(lr, 'mymodel')

    def test_gridsearch(self):
        X, y = make_classification()
        logreg = LogisticRegression(solver='liblinear')
        os.environ['DJANGO_SETTINGS_MODULE'] = ''
        om = Omega()
        om.runtime.celeryapp.conf.CELERY_ALWAYS_EAGER = True
        om.models.put(logreg, 'logreg')
        params = {
            'C': [0.1, 0.5, 1.0]
        }
        # gridsearch on runtimes
        om.runtime.model('logreg').gridsearch(X, y, parameters=params)
        meta = om.models.metadata('logreg')
        # check gridsearch was saved
        self.assertIn('gridsearch', meta.attributes)
        self.assertEqual(len(meta.attributes['gridsearch']), 1)
        self.assertIn('gsModel', meta.attributes['gridsearch'][0])
        # check we can get back the gridsearch model
        gs_model = om.models.get(meta.attributes['gridsearch'][0]['gsModel'])
        self.assertIsInstance(gs_model, GridSearchCV)

    def test_ping(self):
        om = Omega()
        result = om.runtime.ping('foo', fox='bar')
        self.assertIn('message', result)
        self.assertIn('worker', result)
        self.assertEqual(result['args'], ('foo',))
        self.assertEqual(result['kwargs'], dict(fox='bar'))


