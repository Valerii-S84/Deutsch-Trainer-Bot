from __future__ import annotations


ENQUEUE_UPDATE_SCRIPT = """
local dedupe_key = KEYS[1]
local stream_key = KEYS[2]
local ttl_seconds = tonumber(ARGV[1])
local payload = ARGV[2]
local update_id = ARGV[3]
local attempt = ARGV[4]
local redis_time = redis.call('TIME')
local enqueued_at_ms = (tonumber(redis_time[1]) * 1000) + math.floor(tonumber(redis_time[2]) / 1000)

local created = redis.call('SET', dedupe_key, '1', 'EX', ttl_seconds, 'NX')
if not created then
  return {0, ''}
end

local stream_id = redis.call(
  'XADD',
  stream_key,
  '*',
  'payload',
  payload,
  'update_id',
  update_id,
  'enqueued_at_ms',
  enqueued_at_ms,
  'attempt',
  attempt
)
return {1, stream_id}
"""


ENQUEUE_UPDATE_BATCH_SCRIPT = """
local stream_key = KEYS[1]
local ttl_seconds = tonumber(ARGV[1])
local attempt = ARGV[2]
local redis_time = redis.call('TIME')
local enqueued_at_ms = (tonumber(redis_time[1]) * 1000) + math.floor(tonumber(redis_time[2]) / 1000)
local results = {}

for index = 3, #ARGV, 3 do
  local dedupe_key = ARGV[index]
  local payload = ARGV[index + 1]
  local update_id = ARGV[index + 2]
  local created = redis.call('SET', dedupe_key, '1', 'EX', ttl_seconds, 'NX')
  if not created then
    table.insert(results, {0, ''})
  else
    local stream_id = redis.call(
      'XADD',
      stream_key,
      '*',
      'payload',
      payload,
      'update_id',
      update_id,
      'enqueued_at_ms',
      enqueued_at_ms,
      'attempt',
      attempt
    )
    table.insert(results, {1, stream_id})
  end
end

return results
"""
