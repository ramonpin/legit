# -*- coding: utf-8 -*-

"""
legit.cli
~~~~~~~~~

This module provides the CLI interface to legit.
"""
import os
from time import sleep

import click
import clint
from clint.textui import colored, columns
import difflib

from .core import __version__
from .helpers import is_lin, is_osx, is_win
from .scm import SCMRepo
from .settings import settings


CONTEXT_SETTINGS = dict(help_option_names=['-h', '--help'])
pass_scm = click.make_pass_decorator(SCMRepo)


class LegitGroup(click.Group):
    """Custom Group class with specially sorted command list"""

    command_aliases = {
        'pub': 'publish',
        'sw': 'switch',
        'sy': 'sync',
        'unp': 'unpublish',
        'un': 'undo',
    }

    def list_commands(self, ctx):
        commands = super(LegitGroup, self).list_commands(ctx)
        return [cmd for cmd in sort_with_similarity(commands)]

    def get_command(self, ctx, cmd_name):
        rv = click.Group.get_command(self, ctx, cmd_name)
        if rv is not None:
            return rv
        cmd_name = self.command_aliases.get(cmd_name, "")
        return click.Group.get_command(self, ctx, cmd_name)


@click.group(cls=LegitGroup, context_settings=CONTEXT_SETTINGS)
@click.version_option(message='{} {}'.format(colored.yellow('legit'), __version__))
@click.option('--verbose', is_flag=True, help='Enables verbose mode.')
@click.option('--fake', is_flag=True, help='Show but do not invoke git commands.')
@click.pass_context
def cli(ctx, verbose, fake):
    """legit : A Kenneth Reitz Project"""
    # Create a repo object and remember it as as the context object.  From
    # this point onwards other commands can refer to it by using the
    # @pass_scm decorator.
    ctx.obj = SCMRepo()
    ctx.obj.verbose = verbose
    ctx.obj.fake = fake


@cli.command(short_help='Switches to specified branch.')
@click.argument('to_branch', required=False)
@click.option('--verbose', is_flag=True, help='Enables verbose mode.')
@click.option('--fake', is_flag=True, help='Show but do not invoke git commands.')
@pass_scm
def switch(scm, to_branch, verbose, fake):
    """Switches from one branch to another, safely stashing and restoring local changes.
    """
    scm.verbose = verbose
    scm.fake = fake

    if to_branch is None:
        click.echo('Please specify a branch to switch:')
        scm.display_available_branches()
        raise click.Abort

    if scm.repo.is_dirty():
        scm.status_log(scm.stash_it, 'Saving local changes.')

    scm.status_log(scm.checkout_branch, 'Switching to {0}.'.format(
        colored.yellow(to_branch)), to_branch)

    if scm.unstash_index():
        scm.status_log(scm.unstash_it, 'Restoring local changes.')


@cli.command(short_help='Synchronizes the given branch.')
@click.argument('to_branch', required=False)
@click.option('--verbose', is_flag=True, help='Enables verbose mode.')
@click.option('--fake', is_flag=True, help='Show but do not invoke git commands.')
@pass_scm
@click.pass_context
def sync(ctx, scm, to_branch, verbose, fake):
    """Stashes unstaged changes, Fetches remote data, Performs smart
    pull+merge, Pushes local commits up, and Unstashes changes.

    Defaults to current branch.
    """
    scm.verbose = verbose
    scm.fake = fake

    scm.repo_check(require_remote=True)

    if to_branch:
        # Optional branch specifier.
        branch = scm.fuzzy_match_branch(to_branch)
        if branch:
            is_external = True
            original_branch = scm.get_current_branch_name()
        else:
            click.echo("Branch {0} doesn't exist. Use a branch that does."
                       .format(colored.yellow(branch)))
            raise click.Abort
    else:
        # Sync current branch.
        branch = scm.get_current_branch_name()
        is_external = False

    if branch in scm.get_branch_names(local=False):

        if is_external:
            ctx.invoke(switch, to_branch=branch)

        if scm.repo.is_dirty():
            scm.status_log(scm.stash_it, 'Saving local changes.', sync=True)

        scm.status_log(scm.smart_pull, 'Pulling commits from the server.')
        scm.status_log(scm.push, 'Pushing commits to the server.', branch)

        if scm.unstash_index(sync=True):
            scm.status_log(scm.unstash_it, 'Restoring local changes.', sync=True)

        if is_external:
            ctx.invoke(switch, to_branch=original_branch)

    else:
        click.echo('Branch {0} is not published. Publish before syncing.'
                   .format(colored.yellow(branch)))
        raise click.Abort


@cli.command(short_help='Publishes specified branch to the remote.')
@click.argument('to_branch', required=False)
@click.option('--verbose', is_flag=True, help='Enables verbose mode.')
@click.option('--fake', is_flag=True, help='Show but do not invoke git commands.')
@pass_scm
def publish(scm, to_branch, verbose, fake):
    """Pushes an unpublished branch to a remote repository."""
    scm.verbose = verbose
    scm.fake = fake

    scm.repo_check(require_remote=True)
    branch = scm.fuzzy_match_branch(to_branch)

    if not branch:
        branch = scm.get_current_branch_name()
        scm.display_available_branches()
        if to_branch is None:
            click.echo("Using current branch {0}".format(colored.yellow(branch)))
        else:
            click.echo(
                "Branch {0} not found, using current branch {1}"
                .format(colored.red(to_branch), colored.yellow(branch)))

    branch_names = scm.get_branch_names(local=False)

    if branch in branch_names:
        click.echo("Branch {0} is already published. Use a branch that is not published.".format(
            colored.yellow(branch)))
        raise click.Abort

    scm.status_log(scm.publish_branch, 'Publishing {0}.'.format(
        colored.yellow(branch)), branch)


@cli.command(short_help='Removes specified branch from the remote.')
@click.argument('published_branch')
@click.option('--verbose', is_flag=True, help='Enables verbose mode.')
@click.option('--fake', is_flag=True, help='Show but do not invoke git commands.')
@pass_scm
def unpublish(scm, published_branch, verbose, fake):
    """Removes a published branch from the remote repository."""
    scm.verbose = verbose
    scm.fake = fake

    scm.repo_check(require_remote=True)
    branch = scm.fuzzy_match_branch(published_branch)

    if not branch:
        click.echo('Please specify a branch to unpublish:')
        scm.display_available_branches()
        raise click.Abort

    branch_names = scm.get_branch_names(local=False)

    if branch not in branch_names:
        click.echo("Branch {0} isn't published. Use a branch that is published.".format(
            colored.yellow(branch)))
        raise click.Abort

    scm.status_log(scm.unpublish_branch, 'Unpublishing {0}.'.format(
        colored.yellow(branch)), branch)


@cli.command()
@pass_scm
def branches(scm):
    """Get a nice pretty list of branches."""
    scm.display_available_branches()


@cli.command()
@click.option('--verbose', is_flag=True, help='Enables verbose mode.')
@click.option('--fake', is_flag=True, help='Show but do not invoke git commands.')
@pass_scm
def undo(scm, verbose, fake):
    """Removes the last commit from history."""
    scm.verbose = verbose
    scm.fake = fake

    scm.status_log(scm.undo, 'Last commit removed from history.')


@cli.command()
@click.option('--verbose', is_flag=True, help='Enables verbose mode.')
@click.option('--fake', is_flag=True, help='Show but do not invoke git commands.')
@click.pass_context
def install(ctx, verbose, fake):
    """Installs legit git aliases."""

    # aliases = [
    #     'branches',
    #     'publish',
    #     'unpublish',
    #     'switch',
    #     'sync',
    #     'undo'
    # ]

    click.echo('The following git aliases will be installed:\n')
    aliases = cli.list_commands(ctx)
    aliases.remove('install')  # not to be used with git
    for alias in aliases:
        cmd = '!legit ' + alias
        click.echo(columns(['', 1], [colored.yellow('git ' + alias), 20], [cmd, None]))

    if click.confirm('\n{}Install aliases above?'.format('FAKE ' if fake else '')):
        for alias in aliases:
            cmd = '!legit ' + alias
            system_command = 'git config --global --replace-all alias.{0} "{1}"'.format(alias, cmd)
            if fake:
                click.echo(colored.red('Faked! >>> {}'.format(system_command)))
            else:
                if verbose:
                    click.echo(colored.green('>>> {}'.format(system_command)))
                os.system(system_command)
        if not fake:
            click.echo("\nAliases installed.")
    else:
        click.echo("\nAliases will not be installed.")


@cli.command(name="settings")
def cmd_settings():  # command function name is not `settings` to avoid conflict
    """Opens legit settings in editor."""

    path = clint.resources.user.open('config.ini').name

    click.echo('Legit Settings:\n')

    for (option, _, description) in settings.config_defaults:
        click.echo(columns([colored.yellow(option), 25], [description, None]))
    click.echo("")  # separate settings info from os output

    sleep(0.35)

    if is_osx:
        editor = os.environ.get('EDITOR') or os.environ.get('VISUAL') or 'open'
        os.system("{0} '{1}'".format(editor, path))
    elif is_lin:
        editor = os.environ.get('EDITOR') or os.environ.get('VISUAL') or 'pico'
        os.system("{0} '{1}'".format(editor, path))
    elif is_win:
        os.system("\"{0}\"".format(path))
    else:
        click.echo("Edit '{0}' to manage Legit settings.\n".format(path))


@cli.command(name="help")
@click.pass_context
def cmd_help(ctx):  # command function name is not `help` to avoid conflict
    """Display legit help."""
    click.echo(cli.get_help(ctx))


# -------
# Helpers
# -------


def handle_abort(aborted, type=None):
    click.echo('{0} {1}'.format(colored.red('Error:'), aborted.message))
    click.echo(str(aborted.log))
    if type == 'merge':
        click.echo('Unfortunately, there was a merge conflict.'
                   ' It has to be merged manually.')
    elif type == 'unpublish':
        click.echo(
            '''It seems that the remote branch has been already deleted.
            If `legit branches` still list it as published,
            then probably the branch has been deleted at the remote by someone else.
            You can run `git fetch --prune` to update remote information.
            ''')
    raise click.Abort


settings.abort_handler = handle_abort


def sort_with_similarity(iterable, key=None):
    """Sort string list with similarity following original order."""
    if key is None:
        def key(x):
            return x
    ordered = []
    left_iterable = dict(zip([key(elm) for elm in iterable], iterable))
    for k in list(left_iterable.keys()):
        if k not in left_iterable:
            continue
        ordered.append(left_iterable[k])
        del left_iterable[k]
        # find close named iterable
        close_iterable = difflib.get_close_matches(k, left_iterable.keys())
        for close in close_iterable:
            ordered.append(left_iterable[close])
            del left_iterable[close]
    return ordered


def is_verbose(scm):
    return scm.verbose
