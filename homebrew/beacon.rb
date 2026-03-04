class Beacon < Formula
  include Language::Python::Virtualenv

  desc "Network experience monitor — telemetry agent with BXI scoring"
  homepage "https://github.com/skyefugate/Beacon"
  url "https://github.com/skyefugate/Beacon/archive/refs/tags/v0.1.0.tar.gz"
  sha256 "7bbd21fcf6ebcb96b35d4231cbb267c480902f21b9703376ad73855272062f95"
  license "MIT"

  depends_on "python@3.11"

  def install
    virtualenv_install_with_resources

    # Install default config if not present
    etc.install "beacon.yaml" => "beacon/beacon.yaml" unless (etc/"beacon/beacon.yaml").exist?

    # Create data and log directories
    (var/"beacon").mkpath
    (var/"log/beacon").mkpath
  end

  service do
    run [opt_bin/"beacon", "telemetry", "start"]
    keep_alive true
    working_dir var/"beacon"
    log_path var/"log/beacon/agent.log"
    error_log_path var/"log/beacon/agent.log"
    environment_variables BEACON_TELEMETRY_ENABLED: "true",
                          INFLUXDB_URL: "http://127.0.0.1:8086",
                          INFLUXDB_TOKEN: "beacon-dev-token",
                          INFLUXDB_ORG: "beacon"
  end

  def caveats
    <<~EOS
      The beacon telemetry agent runs natively on your Mac to collect
      accurate system metrics (WiFi, DNS, interfaces).

      To start the agent:
        brew services start beacon

      To stop:
        brew services stop beacon

      Configuration:
        #{etc}/beacon/beacon.yaml

      Logs:
        #{var}/log/beacon/agent.log

      The InfluxDB and API/UI components run separately via Docker:
        docker compose up -d
    EOS
  end

  test do
    assert_match "beacon", shell_output("#{bin}/beacon --help")
  end
end
