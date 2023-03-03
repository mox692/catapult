# Copyright 2023 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import absolute_import

import logging
import time
import uuid
from google.appengine.api import app_identity
from google.cloud import monitoring_v3

METRIC_TYPE_PREFIX = "custom.googleapis.com/"
RESOURCE_TYPE = "generic_task"
LOCATION = "us-central1"
NAMESPACE = "Prod"
DEFAULT_TASK_ID = "task_id"
JOB_ID = "job_id"
JOB_TYPE = "job_type"
JOB_STATUS = "job_status"
API_METRIC_TYPE = "api/metrics"
API_NAME = "api_name"
REQUEST_STATUS = "request_status"
RUN_TIME = "run_time"
UUID = "uuid"


def PublishFrozenJobMetric(project_id, job_id, job_type, job_status,
    metric_value=1):
  label_dict = {JOB_ID: job_id, JOB_TYPE: job_type, JOB_STATUS: job_status}
  _PublishTSCloudMetric(project_id, "pinpoint", "pinpoint/job/frozen_job",
                       label_dict, metric_value)


def PublishPinpointJobStatusMetric(project_id,
                                   job_id,
                                   job_type,
                                   job_status,
                                   metric_value=1):
  label_dict = {JOB_ID: job_id, JOB_TYPE: job_type, JOB_STATUS: job_status}
  _PublishTSCloudMetric(project_id, "pinpoint", "pinpoint/job/status_change",
                       label_dict, metric_value)


def PublishPinpointJobRunTimeMetric(project_id, job_id, job_type, job_status,
                                    metric_value):
  label_dict = {JOB_ID: job_id, JOB_TYPE: job_type, JOB_STATUS: job_status}
  _PublishTSCloudMetric(project_id, "pinpoint", "pinpoint/job/run_time",
                       label_dict, metric_value)


def PublishPinpointJobDetailMetrics(project_id,
                                    job_id,
                                    job_type,
                                    job_status,
                                    change_count,
                                    attempt_count,
                                    difference_count=1):
  label_dict = {JOB_ID: job_id, JOB_TYPE: job_type, JOB_STATUS: job_status}
  _PublishTSCloudMetric(project_id, "pinpoint",
                        "pinpoint/job/change_count_per_job", label_dict,
                        change_count)
  _PublishTSCloudMetric(project_id, "pinpoint",
                        "pinpoint/job/attempt_count_per_job", label_dict,
                        attempt_count)
  _PublishTSCloudMetric(project_id, "pinpoint",
                        "pinpoint/job/difference_count_per_job", label_dict,
                        difference_count)


def _PublishTSCloudMetric(project_id,
                         service_name,
                         metric_type,
                         label_dict,
                         metric_value=1):
  client = monitoring_v3.MetricServiceClient()
  project_name = f"projects/{project_id}"

  series = monitoring_v3.TimeSeries()

  series.metric.type = METRIC_TYPE_PREFIX + metric_type

  series.resource.type = RESOURCE_TYPE

  # The identifier of the GCP project associated with this resource,
  # such as "my-project".
  series.resource.labels["project_id"] = project_id

  # The GCP region in which data about the resource is stored
  series.resource.labels["location"] = LOCATION

  # A namespace identifier, such as a cluster name: Dev, Staging or Prod
  series.resource.labels["namespace"] = NAMESPACE

  # An identifier for a grouping of related tasks, such as the name of
  # a microservice or distributed batch job
  series.resource.labels["job"] = service_name

  # A unique identifier for the task within the namespace and job,
  # set default value for this manditory field
  series.resource.labels["task_id"] = DEFAULT_TASK_ID

  for key in label_dict:
    series.metric.labels[key] = label_dict[key]

  now = time.time()
  seconds = int(now)
  nanos = int((now - seconds) * 10**9)
  interval = monitoring_v3.TimeInterval(
      {"end_time": {
          "seconds": seconds,
          "nanos": nanos
      }})
  point = monitoring_v3.Point({
      "interval": interval,
      "value": {
          "double_value": metric_value
      }
  })
  series.points = [point]

  try:
    client.create_time_series(name=project_name, time_series=[series])
  except Exception as e:  # pylint: disable=broad-except
    # Swallow the error from Cloud Monitoring API, the failure from
    # Cloud Monitoring API should not break our code logic.
    logging.warning('Publish data to Cloud Monitoring failed. Error: %s', e)


class APIMetricLogger:

  def __init__(self, service_name, api_name):
    """ This metric logger can be used by the with statement:
    https://peps.python.org/pep-0343/
    """
    self._service_name = service_name
    self._api_name = api_name
    self._start = None
    self.seconds = 0

  def _Now(self):
    return time.time()

  def __enter__(self):
    self._start = self._Now()
    # Currently, Cloud Monitoring allows one write every 5 seconds for any
    # unique tuple (metric_name, metric_label_value_1, metric_label_value_2, …).
    #
    # To avoid being throttled by Cloud Monitoring, add a UUID label_value to
    # make the tuple unique.
    # https://cloud.google.com/monitoring/quotas
    label_dict = {API_NAME: self._api_name, REQUEST_STATUS: "started",
                  UUID: str(uuid.uuid4())}
    _PublishTSCloudMetric(app_identity.get_application_id(), self._service_name,
                          API_METRIC_TYPE, label_dict)

  def __exit__(self, exception_type, exception_value, execution_traceback):
    if exception_type is None:
      # with statement BLOCK runs succeed
      self.seconds = self._Now() - self._start
      logging.info('%s:%s=%f', self._service_name, self._api_name, self.seconds)
      label_dict = {API_NAME: self._api_name, REQUEST_STATUS: "completed",
                    UUID: str(uuid.uuid4())}
      _PublishTSCloudMetric(app_identity.get_application_id(),
                            self._service_name, API_METRIC_TYPE, label_dict,
                            self.seconds)
      return True

    # with statement BLOCK throws exception
    label_dict = {API_NAME: self._api_name, REQUEST_STATUS: "failed",
                  UUID: str(uuid.uuid4())}
    _PublishTSCloudMetric(app_identity.get_application_id(),
                          self._service_name, API_METRIC_TYPE, label_dict)
    # throw out the original exception
    return False


def APIMetric(service_name, api_name):

  def Decorator(wrapped):

    def Wrapper(*a, **kw):
      with APIMetricLogger(service_name, api_name):
        return wrapped(*a, **kw)

    return Wrapper

  return Decorator
