from unittest.mock import patch

from botocore.exceptions import ClientError
from django.test import override_settings

from wiki.lib.cloudfront import invalidate_paths


@override_settings(CLOUDFRONT_DISTRIBUTION_ID="")
@patch("wiki.lib.cloudfront._get_client")
def test_noop_when_distribution_unset(mock_client):
    invalidate_paths(["/c/foo"])
    mock_client.assert_not_called()


@override_settings(CLOUDFRONT_DISTRIBUTION_ID="EXAMPLE123")
@patch("wiki.lib.cloudfront._get_client")
def test_noop_when_paths_empty(mock_client):
    invalidate_paths([])
    mock_client.assert_not_called()


@override_settings(CLOUDFRONT_DISTRIBUTION_ID="EXAMPLE123")
@patch("wiki.lib.cloudfront._get_client")
def test_normalizes_and_dedupes_paths(mock_client):
    invalidate_paths(["foo", "/bar", "/bar", ""])
    mock_client.return_value.create_invalidation.assert_called_once()
    call = mock_client.return_value.create_invalidation.call_args
    assert call.kwargs["DistributionId"] == "EXAMPLE123"
    items = call.kwargs["InvalidationBatch"]["Paths"]["Items"]
    assert items == ["/bar", "/foo"]
    assert call.kwargs["InvalidationBatch"]["Paths"]["Quantity"] == 2
    # CallerReference must be present and non-empty for AWS
    assert call.kwargs["InvalidationBatch"]["CallerReference"]


@override_settings(CLOUDFRONT_DISTRIBUTION_ID="EXAMPLE123")
@patch("wiki.lib.cloudfront._get_client")
def test_swallows_boto_errors(mock_client, caplog):
    mock_client.return_value.create_invalidation.side_effect = ClientError(
        {"Error": {"Code": "AccessDenied", "Message": "nope"}},
        "CreateInvalidation",
    )
    # Must not raise
    invalidate_paths(["/c/foo"])
    assert "CloudFront invalidation failed" in caplog.text


@override_settings(CLOUDFRONT_DISTRIBUTION_ID="EXAMPLE123")
@patch("wiki.lib.cloudfront._get_client")
def test_calls_with_correct_distribution(mock_client):
    invalidate_paths(["/sitemap.xml"])
    call = mock_client.return_value.create_invalidation.call_args
    assert call.kwargs["DistributionId"] == "EXAMPLE123"


@override_settings(CLOUDFRONT_DISTRIBUTION_ID="EXAMPLE123")
@patch("wiki.lib.cloudfront._get_client")
def test_unique_caller_reference_per_call(mock_client):
    invalidate_paths(["/a"])
    invalidate_paths(["/b"])
    refs = [
        c.kwargs["InvalidationBatch"]["CallerReference"]
        for c in mock_client.return_value.create_invalidation.call_args_list
    ]
    assert len(refs) == 2
    assert refs[0] != refs[1]


@override_settings(CLOUDFRONT_DISTRIBUTION_ID="EXAMPLE123")
@patch("wiki.lib.cloudfront._get_client")
def test_strips_query_strings_and_fragments(mock_client):
    """CloudFront keys exclude query strings; sending them wastes a slot."""
    invalidate_paths(["/c/foo?utm=x", "/c/bar#frag"])
    items = mock_client.return_value.create_invalidation.call_args.kwargs[
        "InvalidationBatch"
    ]["Paths"]["Items"]
    assert items == ["/c/bar", "/c/foo"]


@override_settings(CLOUDFRONT_DISTRIBUTION_ID="EXAMPLE123")
@patch("wiki.lib.cloudfront._get_client")
def test_chunks_paths_above_aws_limit(mock_client):
    """AWS caps a batch at 3000 paths; the helper must chunk."""
    paths = [f"/p/{i}" for i in range(3500)]
    invalidate_paths(paths)
    calls = mock_client.return_value.create_invalidation.call_args_list
    assert len(calls) == 2
    assert calls[0].kwargs["InvalidationBatch"]["Paths"]["Quantity"] == 3000
    assert calls[1].kwargs["InvalidationBatch"]["Paths"]["Quantity"] == 500
