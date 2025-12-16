import sys
import time
import yaml
import os
from typing import List, Dict, Optional
from urllib.parse import urlparse, parse_qs
from azure.devops.connection import Connection
from msrest.authentication import BasicAuthentication
from azure.devops.v7_0.pipelines.models import RunPipelineParameters

from utils import checkbox_filter

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
    
    def run_pipeline(self, url: str, stages_to_skip: Optional[List[str]] = None) -> Dict:
        """
        Given an Azure DevOps pipeline definition URL, queue a new build.
        Example URL: https://dev.azure.com/org/project/_build?definitionId=123
        """
        url_info = self._parse_url(url)
        definition_id = int(url_info['query_params'].get("definitionId", [0])[0])
        
        connection = self._get_connection(url_info['organization_url'])
        pipelines_client = connection.clients.get_pipelines_client()
        
        # Configure which stages to skip
        if stages_to_skip is None:
            stages_to_skip = checkbox_filter(
                items=self.get_pipeline_stages(url),
                message="pick the stages to run",
                invert_selections=True
            )
        
        run_parameters = RunPipelineParameters(stages_to_skip=stages_to_skip)
        
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
