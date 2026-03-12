param(
  [string]$HostName = "api.telegram.org",
  [int]$Port = 443
)

Write-Host "[check_bot_dns] host=$HostName port=$Port" -ForegroundColor Cyan

# Use `docker compose run` so we can debug even if the `bot` service is crash-looping.
# We override the entrypoint to a shell and run simple python checks.
$cmd = @'
set -e
echo "--- /etc/resolv.conf ---"
cat /etc/resolv.conf || true

echo "--- resolve (python) ---"
python -c 'import socket,sys; host="__HOST__"; port=__PORT__; print("host=",host,"port=",port);\
try:\
  res=socket.getaddrinfo(host,port);\
  print("resolved=",len(res));\
  print("first=",res[0]);\
  print("second=",res[1] if len(res)>1 else None);\
except Exception as e:\
  print("resolve_error=",repr(e));\
  raise'

echo "--- tcp connect (python) ---"
python -c 'import socket; host="__HOST__"; port=__PORT__;\
try:\
  s=socket.create_connection((host,port),timeout=5);\
  print("tcp_ok");\
  s.close();\
except Exception as e:\
  print("tcp_error=",repr(e));\
  raise'
'@

$cmd = $cmd.Replace('__HOST__', $HostName).Replace('__PORT__', [string]$Port)

# Run a one-off container in the same compose network.
docker compose run --rm --entrypoint sh bot -lc $cmd
