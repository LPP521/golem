import logging
import math
import os
from copy import copy
from typing import Optional
from shutil import copyfile

from golem_messages.message import ComputeTaskDef

from apps.core.task.coretask import (CoreTask,
                                     CoreTaskBuilder,
                                     CoreTaskTypeInfo)
from apps.houdini.houdinienvironment import HoudiniEnvironment
from apps.houdini.task.houdinitaskstate import HoudiniTaskDefaults, HoudiniTaskOptions
from apps.houdini.task.houdinitaskstate import HoudiniTaskDefinition
from apps.houdini.task.houdiniverifier import HoudiniTaskVerifier
from golem.task.taskbase import Task
from golem.task.taskclient import TaskClient
from golem.task.taskstate import SubtaskStatus

logger = logging.getLogger("apps.houdini")


class HoudiniTaskTypeInfo(CoreTaskTypeInfo):
    def __init__(self):
        super().__init__(
            "Houdini",
            HoudiniTaskDefinition,
            HoudiniTaskDefaults(),
            HoudiniTaskOptions,
            HoudiniTaskBuilder
        )



class HoudiniTask(CoreTask):
    ENVIRONMENT_CLASS = HoudiniEnvironment
    VERIFIER_CLASS = HoudiniTaskVerifier

    def __init__(self,
                 total_tasks: int,
                 task_definition: HoudiniTaskDefinition,
                 root_path=None,
                 owner=None):
        super().__init__(
            owner=owner,
            task_definition=task_definition,
            root_path=root_path,
            total_tasks=total_tasks
        )

        self.num_frames = task_definition.options.end_frame - task_definition.options.start_frame

        self.first_frame = task_definition.options.start_frame
        self.next_frame_to_compute = self.first_frame

        self.output_path = ""


    def initialize(self, dir_manager):
        super(HoudiniTask, self).initialize(dir_manager)


    def short_extra_data_repr(self, extra_data):
        return "Dummytask extra_data: {}".format(extra_data)


    def _next_frame_range(self):

        num_subtask_frames = math.ceil( self.num_frames / self.total_tasks )

        start_frame = self.next_frame_to_compute
        end_frame = start_frame + num_subtask_frames

        # If number of frames wasn't divisible by number of tasks, last subtask will compute redundant frames
        if end_frame > ( self.first_frame + self.num_frames ):
            redundant_frames = ( self.first_frame + self.num_frames ) - end_frame

            start_frame = start_frame - redundant_frames
            end_frame = end_frame - redundant_frames

        self.next_frame_to_compute += num_subtask_frames

        # end_frame is last frame that will be rendered
        return start_frame, end_frame - 1


    def _next_task_extra_data(self, perf_index=0.0) -> ComputeTaskDef:

        subtask_id = self.create_subtask_id()

        extra_data = dict()
        extra_data[ "render_params" ] = self.task_definition.options.build_dict()

        render_params = extra_data[ "render_params" ]

        start_frame, end_frame = self._next_frame_range()

        render_params["scene_file"] = os.path.join( "/golem/resources/", os.path.basename( render_params[ "scene_file" ] ) )
        render_params["start_frame"] = start_frame
        render_params["end_frame"] = end_frame
        render_params["output"] = os.path.join( "/golem/output/", render_params[ "output_file" ] )

        return self._new_compute_task_def(subtask_id,
                                          extra_data,
                                          perf_index=perf_index)



    # pylint: disable-msg=too-many-locals
    def query_extra_data(self, perf_index: float, num_cores: int = 0,
                         node_id: Optional[str] = None,
                         node_name: Optional[str] = None) \
            -> Task.ExtraData:


        ctd = self._next_task_extra_data(perf_index)
        sid = ctd['subtask_id']

        self.subtasks_given[sid] = copy(ctd['extra_data'])
        self.subtasks_given[sid]["status"] = SubtaskStatus.starting
        self.subtasks_given[sid]["perf"] = perf_index
        self.subtasks_given[sid]["node_id"] = node_id
        self.subtasks_given[sid]["subtask_id"] = sid

        return self.ExtraData(ctd=ctd)

    def accept_results(self, subtask_id, result_files):
        super().accept_results(subtask_id, result_files)
        node_id = self.subtasks_given[subtask_id]['node_id']
        TaskClient.assert_exists(node_id, self.counting_nodes).accept()
        self.num_tasks_received += 1

        logger.info( "Houdini task finished. Results: " + str( result_files ) )

        for file in result_files[ "results" ]:
            file_name = os.path.basename( file )
            output_file_path = os.path.join( self.task_definition.output_path, file_name )
            copyfile( file, output_file_path )

            logger.info( "Copy file: " + file + " to directory " + self.task_definition.output_path )


    def query_extra_data_for_test_task(self) -> ComputeTaskDef:
        # What performance index should be used ?
        return self._next_task_extra_data( 0.0 )



class HoudiniTaskBuilder(CoreTaskBuilder):
    TASK_CLASS = HoudiniTask

    @classmethod
    def build_dictionary(cls, definition: HoudiniTaskDefinition):
        dictionary = super().build_dictionary(definition)

        opts = dictionary['options']
        opts.update( definition.options.build_dict() )
        opts["output_path"] = definition.output_path

        return dictionary

    @classmethod
    def build_full_definition(cls, task_type: HoudiniTaskDefinition, dictionary):

        definition = super().build_full_definition(task_type, dictionary)

        definition.options.build_from_dictionary( dictionary )

        # Override output_path computed by bas class
        opts = dictionary['options']
        definition.output_path = opts["output_path"]

        return definition
