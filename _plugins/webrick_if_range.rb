# frozen_string_literal: true

# Fix If-Range handling in WEBrick, the server behind `jekyll serve`.
#
# When a browser seeks in a media file it already has partly cached, it sends
# `Range: bytes=N-` with `If-Range: <etag>`, meaning "if the file is unchanged,
# send me that range". WEBrick treats a matching If-Range as "not modified" and
# answers 304 with no body instead of 206 (RFC 9110, section 13.1.5), so the
# read-aloud audio failed after seeking locally. S3 and CloudFront get this
# right; this only changes the local dev server.

require "webrick"

module GctlWebrickIfRange
  def not_modified?(req, res, mtime, etag)
    if (if_range = req["if-range"])
      matches =
        begin
          Time.httpdate(if_range) >= mtime
        rescue ArgumentError
          WEBrick::HTTPUtils.split_header_value(if_range).member?(res["etag"])
        end
      # A matching If-Range means "send the range"; a stale one means "send the whole file".
      req.header.delete("range") unless matches
      req.header.delete("if-range")
    end
    super
  end
end

WEBrick::HTTPServlet::DefaultFileHandler.prepend(GctlWebrickIfRange)
