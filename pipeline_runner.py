import sys
import time
import yaml
import os
from typing import List, Dict, Optional
from urllib.parse import urlparse, parse_qs
from azure.devops.connection import Connection
from msrest.authentication import BasicAuthentication
from azure.devops.v7_0.pipelines.models import RunPipelineParameters, RunResourcesParameters, PipelineResourceParameters

from utils import checkbox_filter, select_from_list

from dotenv import load_dotenv
load_dotenv()


class PipelineRunner:
    """Azure DevOps Pipeline Runner that reuses PAT and connections"""
    
    def __init__(self, pat: str):
        """Initialize with PAT and create connection cache"""
        self.pat = pat
        self._connections: Dict[str, Connection] = {}
    
    def _parse_url(self, url: str) -> Dict:
        """Helper to parse Azure DevOps URLs"""
        parsed = urlparse(url)
        query_params = parse_qs(parsed.query)
        
        return {
            'organization_url': f"{parsed.scheme}://{parsed.netloc}",
            'project': parsed.path.strip("/").split("/")[0],
            'query_params': query_params,
            'parsed': parsed
        }
    
    def _get_connection(self, organization_url: str) -> Connection:
        """Get or create cached connection for an organization"""
        if organization_url not in self._connections:
            credentials = BasicAuthentication("", self.pat)
            self._connections[organization_url] = Connection(
                base_url=organization_url, 
                creds=credentials
            )
        return self._connections[organization_url]
    
    def get_pipeline_stages(self, url: str) -> List[str]:
        """Get all stages from a pipeline definition"""
        url_info = self._parse_url(url)
        definition_id = int(url_info['query_params'].get("definitionId", [0])[0])
        
        connection = self._get_connection(url_info['organization_url'])
        pipelines_client = connection.clients.get_pipelines_client()
        
        # Preview to get the YAML
        run_parameters = RunPipelineParameters()
        preview = pipelines_client.preview(
            run_parameters=run_parameters,
            project=url_info['project'],
            pipeline_id=definition_id
        )
        
        # Parse YAML to extract stages
        pipeline_yaml = yaml.safe_load(preview.final_yaml)
        stages = []
        
        if 'stages' in pipeline_yaml:
            for stage in pipeline_yaml['stages']:
                stage_name = stage.get('stage', stage.get('displayName', 'Unknown'))
                stages.append(stage_name)
        
        return stages
    
    def get_pipeline_resources(self, url: str) -> List[Dict]:
        """Get pipeline resources (other pipelines this pipeline depends on) from a pipeline definition"""
        url_info = self._parse_url(url)
        definition_id = int(url_info['query_params'].get("definitionId", [0])[0])
        
        connection = self._get_connection(url_info['organization_url'])
        pipelines_client = connection.clients.get_pipelines_client()
        
        # Preview to get the YAML
        run_parameters = RunPipelineParameters()
        preview = pipelines_client.preview(
            run_parameters=run_parameters,
            project=url_info['project'],
            pipeline_id=definition_id
        )
        
        # Parse YAML to extract pipeline resources
        pipeline_yaml = yaml.safe_load(preview.final_yaml)
        resources = []
        
        if 'resources' in pipeline_yaml and 'pipelines' in pipeline_yaml['resources']:
            for pipeline_res in pipeline_yaml['resources']['pipelines']:
                resource_info = {
                    'alias': pipeline_res.get('pipeline'),  # The alias used to reference this resource
                    'source': pipeline_res.get('source'),   # The actual pipeline name
                    'project': pipeline_res.get('project', url_info['project']),  # Project (defaults to current)
                }
                resources.append(resource_info)
        
        return resources
    
    def get_pipeline_resource_versions(self, url: str, resource_alias: str, top: int = 20) -> List[Dict]:
        """
        Get available versions (builds) for a pipeline resource.
        
        Args:
            url: Pipeline definition URL
            resource_alias: The alias of the pipeline resource
            top: Number of recent builds to return
            
        Returns:
            List of available builds with id, buildNumber, status, and result
        """
        url_info = self._parse_url(url)
        
        # First get the resource info to find the source pipeline
        resources = self.get_pipeline_resources(url)
        resource = next((r for r in resources if r['alias'] == resource_alias), None)
        
        if not resource:
            raise ValueError(f"Resource '{resource_alias}' not found in pipeline")
        
        connection = self._get_connection(url_info['organization_url'])
        build_client = connection.clients.get_build_client()
        
        # Get the pipeline definition by name
        definitions = build_client.get_definitions(
            project=resource['project'],
            name=resource['source']
        )
        
        if not definitions:
            raise ValueError(f"Pipeline '{resource['source']}' not found in project '{resource['project']}'")
        
        definition_id = definitions[0].id
        
        # Get recent builds for this pipeline
        builds = build_client.get_builds(
            project=resource['project'],
            definitions=[definition_id],
            top=top
        )
        
        return [
            {
                'id': build.id,
                'buildNumber': build.build_number,
                'status': build.status,
                'result': build.result,
                'sourceBranch': build.source_branch,
                'finishTime': str(build.finish_time) if build.finish_time else None
            }
            for build in builds
        ]
    
    def select_resource_versions(self, url: str) -> Optional[Dict[str, str]]:
        """
        Interactive method to select versions for pipeline resources.
        
        Returns:
            Dictionary mapping resource alias to version (build id), or None if no resources
        """
        resources = self.get_pipeline_resources(url)
        
        if not resources:
            return None
        
        print(f"\nFound {len(resources)} pipeline resource(s)")
        
        resource_versions = {}
        
        for resource in resources:
            alias = resource['alias']
            source = resource['source']
            
            print(f"\nResource: {alias} (source: {source})")
            
            try:
                versions = self.get_pipeline_resource_versions(url, alias)
                
                if not versions:
                    print(f"  No builds found for {alias}")
                    continue
                
                # Format choices for selection
                choices = [
                    f"{v['buildNumber']} ({v['result'] or v['status']}) - {v['sourceBranch']} [{v['id']}]"
                    for v in versions
                ]
                choices.insert(0, "[Use default version]")
                
                selected = select_from_list(
                    items=choices,
                    message=f"Select version for '{alias}':"
                )
                
                if selected and selected != "[Use default version]":
                    # Extract build id from selection
                    build_id = selected.split('[')[-1].rstrip(']')
                    resource_versions[alias] = build_id
                    
            except Exception as e:
                print(f"  Could not get versions for {alias}: {e}")
        
        return resource_versions if resource_versions else None

    def get_pipeline_status(self, url: str) -> Dict:
        """
        Given an Azure DevOps pipeline run URL, return its state and result.
        Works with YAML pipeline run URLs like:
        https://dev.azure.com/org/project/_build/results?buildId=123&view=results
        """
        url_info = self._parse_url(url)
        run_id = int(url_info['query_params'].get("buildId", [0])[0])  # YAML runs still use buildId
        
        connection = self._get_connection(url_info['organization_url'])
        build_client = connection.clients.get_build_client()
        build = build_client.get_build(project=url_info['project'], build_id=run_id)
        
        if not build:
            raise ValueError(f"Build {run_id} not found in project {url_info['project']}")
        
        return {
            "run_id": build.id,
            "state": build.status,   # "inProgress", "completed", ...
            "result": build.result   # "succeeded", "failed", ...
        }
    
    def run_pipeline(
        self, 
        url: str, 
        stages_to_skip: Optional[List[str]] = None,
        resource_versions: Optional[Dict[str, str]] = None,
        interactive: bool = True
    ) -> Dict:
        """
        Given an Azure DevOps pipeline definition URL, queue a new build.
        Example URL: https://dev.azure.com/org/project/_build?definitionId=123
        
        Args:
            url: Pipeline definition URL
            stages_to_skip: List of stages to skip (if None and interactive, prompts user)
            resource_versions: Dict mapping resource alias to version/build ID
            interactive: If True, prompts user for stages and resources when not provided
        """
        url_info = self._parse_url(url)
        definition_id = int(url_info['query_params'].get("definitionId", [0])[0])
        
        connection = self._get_connection(url_info['organization_url'])
        pipelines_client = connection.clients.get_pipelines_client()
        
        # Configure which stages to skip
        if stages_to_skip is None and interactive:
            stages_to_skip = checkbox_filter(
                items=self.get_pipeline_stages(url),
                message="pick the stages to run",
                invert_selections=True
            )
        
        # Configure resource versions
        if resource_versions is None and interactive:
            resource_versions = self.select_resource_versions(url)
        
        # Build resources parameter if resource versions specified
        resources_param = None
        if resource_versions:
            pipelines_resources = {
                alias: PipelineResourceParameters(version=version)
                for alias, version in resource_versions.items()
            }
            resources_param = RunResourcesParameters(pipelines=pipelines_resources)
        
        run_parameters = RunPipelineParameters(
            stages_to_skip=stages_to_skip or [],
            resources=resources_param
        )
        
        # Run the pipeline
        run = pipelines_client.run_pipeline(
            run_parameters=run_parameters,
            project=url_info['project'],
            pipeline_id=definition_id
        )
        
        # Build browser-friendly URL for the run
        browser_url = f"{url_info['organization_url']}/{url_info['project']}/_build/results?buildId={run.id}&view=results"
        
        return {
            "build_id": run.id,
            "url": browser_url
        }
    
    def monitor_and_trigger(self, monitor_url: str, trigger_url: str, check_interval: int = 30):
        """
        Monitor a pipeline and trigger another when the first one completes.
        
        Args:
            monitor_url: URL of the pipeline run to monitor
            trigger_url: URL of the pipeline definition to trigger
            check_interval: Seconds between status checks (default: 30)
        """
        print("Starting pipeline monitor...")
        print(f"Monitoring: {monitor_url}")
        print(f"Will trigger: {trigger_url}")
        print(f"Check interval: {check_interval} seconds\n")
        
        # Ask which stages to run for the second pipeline BEFORE monitoring starts
        print("Preparing second pipeline configuration...")
        stages_to_skip = checkbox_filter(
            items=self.get_pipeline_stages(trigger_url),
            message="Pick the stages to run for the second pipeline",
            invert_selections=True
        )
        print(f"Configuration saved. Will skip stages: {stages_to_skip if stages_to_skip else 'None'}\n")
        print("Now monitoring first pipeline...")
        
        try:
            while True:
                try:
                    status = self.get_pipeline_status(monitor_url)
                    print(f"Pipeline {status['run_id']} status: {status['state']}")
                    
                    if status['result']:
                        print(f"Pipeline result: {status['result']}")
                    
                    if status['state'] == 'completed':
                        print(f"\nPipeline {status['run_id']} completed with result: {status['result']}")
                        if status['result'] == 'succeeded':
                            print("Triggering second pipeline with pre-selected stages...")
                            
                            trigger_result = self.run_pipeline(trigger_url, stages_to_skip=stages_to_skip)
                            print(f"Successfully triggered pipeline {trigger_result['build_id']}")
                            print(f"URL: {trigger_result['url']}")
                        else:
                            print(f"Pipeline {status['run_id']} failed with result: {status['result']}")
                        break
                    
                    # Get the current time
                    curr_time = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())
                    print(f"[{curr_time}] Pipeline still running. Checking again in {check_interval} seconds...")
                    time.sleep(check_interval)
                    
                except KeyboardInterrupt:
                    print("\nMonitoring interrupted by user")
                    sys.exit(0)
                except Exception as e:
                    print(f"Error checking pipeline status: {e}")
                    print(f"Retrying in {check_interval} seconds...")
                    time.sleep(check_interval)
                    
        except Exception as e:
            print(f"Fatal error: {e}")
            sys.exit(1)


# Backward compatibility functions
def get_pipeline_stages(url: str, pat: str) -> List[str]:
    """Backward compatibility wrapper for get_pipeline_stages"""
    runner = PipelineRunner(pat)
    return runner.get_pipeline_stages(url)


def get_pipeline_status_from_url(url: str, pat: str) -> Dict:
    """Backward compatibility wrapper for get_pipeline_status"""
    runner = PipelineRunner(pat)
    return runner.get_pipeline_status(url)


def run_pipeline_from_url(url: str, pat: str, stagedToSkip: List[str] = None) -> Dict:
    """Backward compatibility wrapper for run_pipeline"""
    runner = PipelineRunner(pat)
    return runner.run_pipeline(url, stagedToSkip)


def monitor_and_trigger(monitor_url: str, trigger_url: str, pat: str, check_interval: int = 30):
    """Backward compatibility wrapper for monitor_and_trigger"""
    runner = PipelineRunner(pat)
    return runner.monitor_and_trigger(monitor_url, trigger_url, check_interval)


if __name__ == "__main__":
    pr = "https://msazure.visualstudio.com/One/_build/results?buildId=137041397&view=results"
    prod_release = "https://msazure.visualstudio.com/One/_build?definitionId=373994"
    # get your pat token from https://msazure.visualstudio.com/_usersSettings/tokens
    pat = os.getenv("ADO_PAT")
    
    # Use the new class-based approach
    runner = PipelineRunner(pat)
    runner.monitor_and_trigger(pr, prod_release)
