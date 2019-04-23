from abc import ABC, abstractmethod
from enum import Enum
from functools import wraps
from logging import Logger, getLogger
from threading import Lock
from typing import Any, Callable, Dict, List, Optional, NamedTuple, Union, \
    Sequence

from twisted.internet.defer import Deferred

from golem.core.simpleserializer import DictSerializable

CounterId = str
CounterUsage = Any

EnvId = str

EnvEventId = str
EnvEvent = Any  # TODO: Define environment events

RuntimeEventId = str
RuntimeEvent = Any  # TODO: Define runtime events


class EnvConfig(DictSerializable, ABC):
    """ Environment-wide configuration. Specifies e.g. available resources. """


class Prerequisites(DictSerializable, ABC):
    """
    Environment-specific requirements for computing a task. Distributed with the
    task header. Providers are expected to prepare (download, install, etc.)
    prerequisites in advance not to waste computation time.
    """


class Payload(DictSerializable, ABC):
    """
    A definition for Runtime. Environment-specific description of computation to
    be run. Received when provider is assigned a subtask.
    """


class EnvSupportStatus(NamedTuple):
    """ Is the environment supported? If not, why? """
    supported: bool
    nonsupport_reason: Optional[str] = None


class RuntimeStatus(Enum):
    CREATED = 0
    PREPARING = 1
    PREPARED = 2
    STARTING = 3
    RUNNING = 4
    STOPPED = 5
    CLEANING_UP = 6
    TORN_DOWN = 7
    FAILURE = 8

    def __str__(self) -> str:
        return self.name


class Runtime(ABC):
    """ A runnable object representing some particular computation. Tied to a
        particular Environment that was used to create this object. """

    def __init__(self, logger: Optional[Logger] = None) -> None:
        self._logger = logger or getLogger(__name__)
        self._status = RuntimeStatus.CREATED
        self._status_lock = Lock()

    def _change_status(
            self,
            from_status: Union[RuntimeStatus, Sequence[RuntimeStatus]],
            to_status: RuntimeStatus) -> None:
        """ Assert that current Runtime status is the given one and change to
            another one. Using lock to ensure atomicity. """

        if isinstance(from_status, RuntimeStatus):
            from_status = [from_status]

        with self._status_lock:
            if self._status not in from_status:
                exp_status = " or ".join(map(str, from_status))
                raise ValueError(
                    f"Invalid status: {self._status}. Expected: {exp_status}")
            self._status = to_status

    def _wrap_status_change(
            self,
            success_status: RuntimeStatus,
            error_status: RuntimeStatus = RuntimeStatus.FAILURE,
            success_msg: Optional[str] = None,
            error_msg: Optional[str] = None
    ) -> Callable[[Callable[[], None]], Callable[[], None]]:
        """ Wrap function. If it fails log error_msg, set status to
            error_status, and re-raise the exception. Otherwise log success_msg
            and set status to success_status. Setting status uses lock. """

        def wrapper(func: Callable[[], None]):

            @wraps(func)
            def wrapped():
                try:
                    func()
                except Exception:
                    if error_msg:
                        self._logger.exception(error_msg)
                    with self._status_lock:
                        self._status = error_status
                    raise
                else:
                    if success_msg:
                        self._logger.info(success_msg)
                    with self._status_lock:
                        self._status = success_status

            return wrapped

        return wrapper

    @abstractmethod
    def prepare(self) -> Deferred:
        """ Prepare the Runtime to be started. Assumes current status is
            'CREATED'. """
        raise NotImplementedError

    @abstractmethod
    def cleanup(self) -> Deferred:
        """ Clean up after the Runtime has finished running. Assumes current
            status is 'STOPPED' or 'FAILURE'. In the latter case it is not
            guaranteed that the cleanup will be successful. """
        raise NotImplementedError

    @abstractmethod
    def start(self) -> Deferred:
        """ Start the computation. Assumes current status is 'PREPARED'. """
        raise NotImplementedError

    @abstractmethod
    def stop(self) -> Deferred:
        """ Interrupt the computation. Assumes current status is 'RUNNING'. """
        raise NotImplementedError

    def status(self) -> RuntimeStatus:
        """ Get the current status of the Runtime. """
        with self._status_lock:
            return self._status

    @abstractmethod
    def usage_counters(self) -> Dict[CounterId, CounterUsage]:
        """ For each usage counter supported by the Environment (e.g. clock
            time) get current usage by this Runtime. """
        raise NotImplementedError

    @abstractmethod
    def listen(self, event_id: RuntimeEventId,
               callback: Callable[[RuntimeEvent], Any]) -> None:
        """ Register a listener for a given type of Runtime events. """
        raise NotImplementedError

    @abstractmethod
    def call(self, alias: str, *args, **kwargs) -> Deferred:
        """ Send RPC call to the Runtime. """
        raise NotImplementedError


class EnvMetadata(NamedTuple):
    id: EnvId
    description: str
    supported_counters: List[CounterId]
    custom_metadata: Dict[str, Any]


class EnvStatus(Enum):
    DISABLED = 0
    PREPARING = 1
    ENABLED = 2
    CLEANING_UP = 3
    # TODO: Add 'ERROR' status?

    def __str__(self) -> str:
        return self.name


class Environment(ABC):
    """ An Environment capable of running computations. It is responsible for
        creating Runtimes. """

    @classmethod
    @abstractmethod
    def supported(cls) -> EnvSupportStatus:
        """ Is the Environment supported on this machine? """
        raise NotImplementedError

    @abstractmethod
    def status(self) -> EnvStatus:
        """ Get current status of the Environment. """
        raise NotImplementedError

    @abstractmethod
    def prepare(self) -> Deferred:
        """ Activate the Environment. Assumes current status is 'DISABLED'. """
        raise NotImplementedError

    @abstractmethod
    def cleanup(self) -> Deferred:
        """ Deactivate the Environment. Assumes current status is 'ENABLED'. """
        raise NotImplementedError

    @classmethod
    @abstractmethod
    def metadata(cls) -> EnvMetadata:
        """ Get Environment metadata. """
        raise NotImplementedError

    @classmethod
    @abstractmethod
    def parse_prerequisites(cls, prerequisites_dict: Dict[str, Any]) \
            -> Prerequisites:
        """ Build Prerequisites struct from supplied dictionary. Returned value
            is of appropriate type for calling install_prerequisites(). """
        raise NotImplementedError

    @abstractmethod
    def install_prerequisites(self, prerequisites: Prerequisites) -> Deferred:
        """ Prepare Prerequisites for running a computation. Assumes current
            status is 'ENABLED'. """
        raise NotImplementedError

    @classmethod
    @abstractmethod
    def parse_config(cls, config_dict: Dict[str, Any]) -> EnvConfig:
        """ Build config struct from supplied dictionary. Returned value
            is of appropriate type for calling update_config(). """
        raise NotImplementedError

    @abstractmethod
    def config(self) -> EnvConfig:
        """ Get current configuration of the Environment. """
        raise NotImplementedError

    @abstractmethod
    def update_config(self, config: EnvConfig) -> None:
        """ Update configuration. Assumes current status is 'DISABLED'. """
        raise NotImplementedError

    @abstractmethod
    def listen(self, event_id: EnvEventId,
               callback: Callable[[EnvEvent], Any]) -> None:
        """ Register a listener for a given type of Environment events. """
        raise NotImplementedError

    @classmethod
    @abstractmethod
    def parse_payload(cls, payload_dict: Dict[str, Any]) \
            -> Payload:
        """ Build Payload struct from supplied dictionary. Returned value
            is of appropriate type for calling runtime(). """
        raise NotImplementedError

    @abstractmethod
    def runtime(self, payload: Payload, config: Optional[EnvConfig] = None) \
            -> Runtime:
        """ Create a Runtime from the given Payload. Optionally, override
            current config with the supplied one (it is however not guaranteed
            that all config parameters could be overridden). Assumes current
            status is 'ENABLED'. """
        raise NotImplementedError
