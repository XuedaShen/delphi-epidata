"""Integration tests for acquisition of COVID hospitalization."""

# standard library
from datetime import date
import unittest
from unittest.mock import patch

# third party
from freezegun import freeze_time
import pandas as pd

# first party
from delphi.epidata.acquisition.covid_hosp.state_daily.database import Database
from delphi.epidata.acquisition.covid_hosp.common.test_utils import UnitTestUtils
from delphi.epidata.client.delphi_epidata import Epidata
from delphi.epidata.acquisition.covid_hosp.state_daily.update import Update
from delphi.epidata.acquisition.covid_hosp.state_daily.network import Network
from delphi.epidata.acquisition.covid_hosp.common.utils import Utils
import delphi.operations.secrets as secrets

# py3tester coverage target (equivalent to `import *`)
__test_target__ = \
    'delphi.epidata.acquisition.covid_hosp.state_daily.update'


class AcquisitionTests(unittest.TestCase):

  def setUp(self):
    """Perform per-test setup."""

    # configure test data
    self.test_utils = UnitTestUtils(__file__)

    # use the local instance of the Epidata API
    Epidata.BASE_URL = 'http://delphi_web_epidata/epidata'
    Epidata.auth = ('epidata', 'key')

    # use the local instance of the epidata database
    secrets.db.host = 'delphi_database_epidata'
    secrets.db.epi = ('user', 'pass')

    # clear relevant tables
    with Database.connect() as db:
      with db.new_cursor() as cur:
        cur.execute('truncate table covid_hosp_state_timeseries')
        cur.execute('truncate table covid_hosp_meta')
        cur.execute('delete from api_user')
        cur.execute('insert into api_user(api_key, email) values("key", "email")')

  def get_modified_dataset(self, critical_staffing_shortage_today_yes, reporting_cutoff_start):
    """Get a simplified version of a test dataset.

    Only WY data is modified. The issue date is specified in the metadata file.
    """
    df = self.test_utils.load_sample_dataset()
    df_new = pd.DataFrame(df[df["state"] == "WY"], columns=df.columns).reset_index(drop=True)
    df_new["critical_staffing_shortage_today_yes"] = critical_staffing_shortage_today_yes
    df_new["reporting_cutoff_start"] = reporting_cutoff_start
    return df_new

  def test_acquire_dataset(self):
    """Acquire a new dataset."""

    with freeze_time("2021-03-15"):
      # make sure the data does not yet exist
      with self.subTest(name='no data yet'):
        response = Epidata.covid_hosp('MA', Epidata.range(20200101, 20210101))
        self.assertEqual(response['result'], -2, response)

      # acquire sample data into local database
      # mock out network calls to external hosts
      # issues: 3/13, 3/15
      with self.subTest(name='first acquisition'), \
          patch.object(Network, 'fetch_metadata',
                       return_value=self.test_utils.load_sample_metadata("metadata.csv")) as mock_fetch_meta, \
          patch.object(Network, 'fetch_dataset', side_effect=[
            self.test_utils.load_sample_dataset(),
            self.test_utils.load_sample_dataset()
          ]) as mock_fetch:
        acquired = Update.run()
        self.assertTrue(acquired)
        self.assertEqual(mock_fetch_meta.call_count, 1)

      # make sure the data now exists
      with self.subTest(name='initial data checks'):
        response = Epidata.covid_hosp('WY', Epidata.range(20200101, 20210101))
        self.assertEqual(response['result'], 1)
        self.assertEqual(len(response['epidata']), 1)
        row = response['epidata'][0]
        self.assertEqual(row['state'], 'WY')
        self.assertEqual(row['date'], 20201209)
        self.assertEqual(row['issue'], 20210315) # include today's data by default
        self.assertEqual(row['critical_staffing_shortage_today_yes'], 8)
        self.assertEqual(row['total_patients_hospitalized_confirmed_influenza_covid_coverage'], 56)
        self.assertIsNone(row['critical_staffing_shortage_today_no'])

        # expect 61 fields per row (63 database columns, except `id` and `record_type`)
        self.assertEqual(len(row), 118)

      with self.subTest(name='all date batches acquired'):
        response = Epidata.covid_hosp('WY', Epidata.range(20200101, 20210101), issues=20210313)
        self.assertEqual(response['result'], 1)

      # re-acquisition of the same dataset should be a no-op
      # issues: 3/13, 3/15
      with self.subTest(name='second acquisition'), \
          patch.object(Network, 'fetch_metadata',
                       return_value=self.test_utils.load_sample_metadata("metadata.csv")) as mock_fetch_meta, \
          patch.object(Network, 'fetch_dataset', side_effect=[
            self.test_utils.load_sample_dataset(),
            self.test_utils.load_sample_dataset()
          ]) as mock_fetch:
        acquired = Update.run()
        self.assertFalse(acquired)

        # make sure the data still exists
        response = Epidata.covid_hosp('WY', Epidata.range(20200101, 20210101))
        self.assertEqual(response['result'], 1)
        self.assertEqual(len(response['epidata']), 1)

    with freeze_time("2021-03-16"):
      # simulate issue posted after yesterday's run
      with self.subTest(name='late issue posted'), \
          patch.object(Network, 'fetch_metadata',
                      return_value=self.test_utils.load_sample_metadata("metadata2.csv")) as mock_fetch_meta, \
          patch.object(Network, 'fetch_dataset', side_effect=[
            self.get_modified_dataset(critical_staffing_shortage_today_yes = 9, reporting_cutoff_start="2020-12-09"),
            self.get_modified_dataset(critical_staffing_shortage_today_yes = 10, reporting_cutoff_start="2020-12-09"),
            self.get_modified_dataset(critical_staffing_shortage_today_yes = 11, reporting_cutoff_start="2020-12-10"),
            self.get_modified_dataset(critical_staffing_shortage_today_yes = 12, reporting_cutoff_start="2020-12-10"),
          ]) as mock_fetch:
        acquired = Update.run()
        self.assertTrue(acquired)
        self.assertEqual(mock_fetch_meta.call_count, 1)

      # make sure everything was filed correctly
      with self.subTest(name='late issue data checks'):
        response = Epidata.covid_hosp('WY', Epidata.range(20200101, 20210101))
        self.assertEqual(response['result'], 1)
        self.assertEqual(len(response['epidata']), 2)

        # should have data from 03-15 00:00:01AM
        row = response['epidata'][0]
        self.assertEqual(row['state'], 'WY')
        self.assertEqual(row['date'], 20201209)
        self.assertEqual(row['issue'], 20210315) # include today's data by default
        self.assertEqual(row['critical_staffing_shortage_today_yes'], 10)
        self.assertEqual(row['total_patients_hospitalized_confirmed_influenza_covid_coverage'], 56)
        self.assertIsNone(row['critical_staffing_shortage_today_no'])

        # should have data from 03-16 00:00:01AM
        row = response['epidata'][1]
        self.assertEqual(row['state'], 'WY')
        self.assertEqual(row['date'], 20201210)
        self.assertEqual(row['issue'], 20210316) # include today's data by default
        self.assertEqual(row['critical_staffing_shortage_today_yes'], 12)
        self.assertEqual(row['total_patients_hospitalized_confirmed_influenza_covid_coverage'], 56)
        self.assertIsNone(row['critical_staffing_shortage_today_no'])

        # expect 61 fields per row (63 database columns, except `id` and `record_type`)
        self.assertEqual(len(row), 118)

      with self.subTest(name='all date batches acquired'):
        response = Epidata.covid_hosp('WY', Epidata.range(20200101, 20210101), issues=20210316)
        self.assertEqual(response['result'], 1)


  @freeze_time("2021-03-16")
  def test_acquire_specific_issue(self):
    """Acquire a new dataset."""

    # make sure the data does not yet exist
    with self.subTest(name='no data yet'):
      response = Epidata.covid_hosp('MA', Epidata.range(20200101, 20210101))
      self.assertEqual(response['result'], -2)

    # acquire sample data into local database
    # mock out network calls to external hosts
    with Database.connect() as db:
      pre_max_issue = db.get_max_issue()
    self.assertEqual(pre_max_issue, pd.Timestamp('1900-01-01 00:00:00'))
    with self.subTest(name='first acquisition'), \
         patch.object(Network, 'fetch_metadata', return_value=self.test_utils.load_sample_metadata()) as mock_fetch_meta, \
         patch.object(Network, 'fetch_dataset', side_effect=[self.test_utils.load_sample_dataset()]
                      ) as mock_fetch:
      acquired = Utils.update_dataset(Database,
                                      Network,
                                      date(2021, 3, 12),
                                      date(2021, 3, 14))
      with Database.connect() as db:
        post_max_issue = db.get_max_issue()
      self.assertEqual(post_max_issue, pd.Timestamp('2021-03-13 00:00:00'))
      self.assertTrue(acquired)
