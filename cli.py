import os
import click
import typer
from pipeline_runner import PipelineRunner
from dotenv import load_dotenv

load_dotenv()

HELP_TEXT = """Azure DevOps Pipeline Runner - Monitor and trigger pipelines.

A CLI tool to monitor Azure DevOps pipeline runs and trigger subsequent pipelines.

\b
AUTHENTICATION:
  PAT with 'Build (Read & Execute)' permissions required.
  Create: https://msazure.visualstudio.com/_usersSettings/tokens
  Docs:   https://learn.microsoft.com/en-us/azure/devops/organizations/accounts/use-personal-access-tokens-to-authenticate
  Set via ADO_PAT env var or --pat option.
"""

EPILOG_TEXT = """

EXAMPLES:\n
  piperun run <pipeline-to-run>\n
  piperun run <pipeline-to-run> --pat <token>\n
  piperun monitor-trigger <wait-for-run> <then-trigger> --pat <token>\n
  piperun monitor-trigger <wait-for-run> <then-trigger> --interval 60\n
\nURL FORMATS:\n
  <wait-for-run>  (buildId):      https://dev.azure.com/org/proj/_build/results?buildId=123\n
  <then-trigger>  (definitionId): https://dev.azure.com/org/proj/_build?definitionId=456\n
  <pipeline-to-run> same as <then-trigger>\n
"""

# Create the main app with subcommands
app = typer.Typer(
    name="piperun",
    help=HELP_TEXT,
    epilog=EPILOG_TEXT,
    no_args_is_help=True,
    # rich_markup_mode=None,
    context_settings={"max_content_width": 120},
)


@app.command("monitor-trigger")
def monitor_trigger(
    wait_for: str = typer.Argument(
        ...,
        help="URL of the pipeline run to wait for (e.g., https://dev.azure.com/org/project/_build/results?buildId=123)",
    ),
    pipeline_to_trigger: str = typer.Argument(
        ...,
        help="URL of the pipeline definition to trigger (e.g., https://dev.azure.com/org/project/_build?definitionId=456)",
    ),
    pat: str = typer.Option(
        os.getenv("ADO_PAT"),
        "--pat",
        help="Personal Access Token for Azure DevOps. Create at: https://dev.azure.com/{org}/_usersSettings/tokens",
        show_default=False,
    ),
    interval: int = typer.Option(
        30,
        "--interval",
        "-i",
        help="Check interval in seconds",
    ),
):
    """
    Monitor an Azure DevOps pipeline run until completion, then trigger another pipeline.

    This command waits for the specified pipeline run to complete. If it succeeds,
    it will automatically trigger the target pipeline. You'll be prompted to select
    which stages to run before monitoring begins.
    """
    if not pat:
        typer.echo("Error: PAT is required. Set ADO_PAT environment variable or use --pat option.")
        typer.echo("Create a PAT at: https://dev.azure.com/{your-org}/_usersSettings/tokens")
        raise typer.Exit(1)

    runner = PipelineRunner(pat)
    runner.monitor_and_trigger(wait_for, pipeline_to_trigger, interval)


@app.command("run")
def run_pipeline(
    pipeline_url: str = typer.Argument(
        ...,
        help="URL of the pipeline definition to run (e.g., https://dev.azure.com/org/project/_build?definitionId=456)",
    ),
    pat: str = typer.Option(
        os.getenv("ADO_PAT"),
        "--pat",
        help="Personal Access Token for Azure DevOps. Create at: https://dev.azure.com/{org}/_usersSettings/tokens",
        show_default=False,
    ),
):
    """
    Run an Azure DevOps pipeline directly.

    This command triggers a pipeline run immediately. You'll be prompted to select
    which stages to run.
    """
    if not pat:
        typer.echo("Error: PAT is required. Set ADO_PAT environment variable or use --pat option.")
        typer.echo("Create a PAT at: https://dev.azure.com/{your-org}/_usersSettings/tokens")
        raise typer.Exit(1)

    runner = PipelineRunner(pat)
    
    typer.echo(f"Triggering pipeline: {pipeline_url}")
    result = runner.run_pipeline(pipeline_url)
    
    typer.echo(f"\nSuccessfully triggered pipeline!")
    typer.echo(f"Build ID: {result['build_id']}")
    typer.echo(f"URL: {result['url']}")


def main():
    """Entry point for the CLI."""
    app()


if __name__ == "__main__":
    main()
