"""Tests for lib"""
from datetime import datetime, timezone
from unittest.mock import (
    Mock,
    patch,
)

from requests import Response, HTTPError
import pytest

from github import github_auth_headers
from lib import (
    get_release_pr,
    get_unchecked_authors,
    match_user,
    next_workday_at_10,
    parse_checkmarks,
    reformatted_full_name,
    ReleasePR,
    url_with_access_token,
)


FAKE_RELEASE_PR_BODY = """

## Alice Pote
  - [x] Implemented AutomaticEmail API ([5de04973](../commit/5de049732f769ec8a2a24068514603f353e13ed4))
  - [ ] Unmarked some files as executable ([c665a2c7](../commit/c665a2c79eaf5e2d54b18f5a880709f5065ed517))

## Nathan Levesque
  - [x] Fixed seed data for naive timestamps (#2712) ([50d19c4a](../commit/50d19c4adf22c5ddc8b8299f4b4579c2b1e35b7f))
  - [garbage] xyz
    """

OTHER_PR = {
    "url": "https://api.github.com/repos/mitodl/micromasters/pulls/2985",
    "html_url": "https://github.com/mitodl/micromasters/pull/2985",
    "body": "not a release",
    "title": "not a release",
    "head": {
        "ref": "other-branch"
    },
}
RELEASE_PR = {
    "url": "https://api.github.com/repos/mitodl/micromasters/pulls/2993",
    "html_url": "https://github.com/mitodl/micromasters/pull/2993",
    "body": FAKE_RELEASE_PR_BODY,
    "title": "Release 0.53.3",
    "head": {
        "ref": "release-candidate"
    },
}
FAKE_PULLS = [OTHER_PR, RELEASE_PR]


def test_parse_checkmarks():
    """parse_checkmarks should look up the Release PR body and return a list of commits"""
    assert parse_checkmarks(FAKE_RELEASE_PR_BODY) == [
        {
            'checked': True,
            'author_name': 'Alice Pote',
            'title': 'Implemented AutomaticEmail API'
        },
        {
            'checked': False,
            'author_name': 'Alice Pote',
            'title': 'Unmarked some files as executable'
        },
        {
            'checked': True,
            'author_name': 'Nathan Levesque',
            'title': 'Fixed seed data for naive timestamps (#2712)'
        },
    ]


def test_get_release_pr():
    """get_release_pr should grab a release from GitHub's API"""
    org = 'org'
    repo = 'repo'
    access_token = 'access'

    with patch('github.requests.get', return_value=Mock(json=Mock(return_value=FAKE_PULLS))) as get_mock:
        pr = get_release_pr(access_token, org, repo)
    get_mock.assert_called_once_with("https://api.github.com/repos/{org}/{repo}/pulls".format(
        org=org,
        repo=repo,
    ), headers=github_auth_headers(access_token))
    assert pr.body == RELEASE_PR['body']
    assert pr.url == RELEASE_PR['html_url']
    assert pr.version == '0.53.3'


def test_get_release_pr_no_pulls():
    """If there is no release PR it should return None"""
    with patch(
        'github.requests.get', return_value=Mock(json=Mock(return_value=[OTHER_PR]))
    ):
        assert get_release_pr('access_token', 'org', 'repo-missing') is None


def test_too_many_releases():
    """If there is no release PR, an exception should be raised"""
    pulls = [RELEASE_PR, RELEASE_PR]
    with pytest.raises(Exception) as ex, patch(
        'github.requests.get', return_value=Mock(json=Mock(return_value=pulls))
    ):
        get_release_pr('access_token', 'org', 'repo')

    assert ex.value.args[0] == "More than one pull request for the branch release-candidate"


def test_no_release_wrong_repo():
    """If there is no repo accessible, an exception should be raised"""
    response_404 = Response()
    response_404.status_code = 404
    with pytest.raises(HTTPError) as ex, patch(
        'github.requests.get', return_value=response_404
    ):
        get_release_pr('access_token', 'org', 'repo')

    assert ex.value.response.status_code == 404


def test_get_unchecked_authors():
    """
    get_unchecked_authors should download the PR body, parse it,
    filter out checked authors and leave only unchecked ones
    """
    org = 'org'
    repo = 'repo'
    access_token = 'all-access'

    with patch('lib.get_release_pr', autospec=True, return_value=ReleasePR(
        body=FAKE_RELEASE_PR_BODY,
        version='1.2.3',
        url='http://url'
    )) as get_release_pr_mock:
        unchecked = get_unchecked_authors(access_token, org, repo)
    assert unchecked == {"Alice Pote"}
    get_release_pr_mock.assert_called_once_with(access_token, org, repo)


def test_next_workday_at_10():
    """next_workday_at_10 should get the time that's tomorrow at 10am, or Monday if that's the next workday"""
    saturday_at_8am = datetime(2017, 4, 1, 8, tzinfo=timezone.utc)
    assert next_workday_at_10(saturday_at_8am) == datetime(2017, 4, 3, 10, tzinfo=timezone.utc)
    tuesday_at_4am = datetime(2017, 4, 4, 4, tzinfo=timezone.utc)
    assert next_workday_at_10(tuesday_at_4am) == datetime(2017, 4, 5, 10, tzinfo=timezone.utc)
    wednesday_at_3pm = datetime(2017, 4, 5, 15, tzinfo=timezone.utc)
    assert next_workday_at_10(wednesday_at_3pm) == datetime(2017, 4, 6, 10, tzinfo=timezone.utc)


def test_reformatted_full_name():
    """reformatted_full_name should take the first and last names and make it lowercase"""
    assert reformatted_full_name("") == ""
    assert reformatted_full_name("George") == "george"
    assert reformatted_full_name("X Y Z A B") == "x b"


FAKE_SLACK_USERS = [
    {
        'profile': {
            'real_name': 'George Schneeloch',
        },
        'name': 'gschneel',
        'id': 'U12345',
    },
    {
        'profile': {
            'real_name': 'Sar Haidar'
        },
        'name': 'shaidar',
        'id': 'U65432'
    },
    {
        'profile': {
            'real_name': 'Sarah H'
        },
        'name': 'sarahh',
        'id': 'U13986'
    },
]


def test_match_users():
    """match_users should use the Levensthein distance to compare usernames"""
    assert match_user(FAKE_SLACK_USERS, "George Schneeloch") == "<@U12345>"
    assert match_user(FAKE_SLACK_USERS, "George Schneelock") == "<@U12345>"
    assert match_user(FAKE_SLACK_USERS, "George") == "<@U12345>"
    assert match_user(FAKE_SLACK_USERS, 'sar') == '<@U65432>'


def test_url_with_access_token():
    """url_with_access_token should insert the access token into the url"""
    assert url_with_access_token(
        "access", "http://github.com/mitodl/release-script.git"
    ) == "https://access@github.com/mitodl/release-script.git"
