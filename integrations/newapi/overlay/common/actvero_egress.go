package common

import (
	"context"
	"errors"
	"net"
	"net/http"
	"os"
	"strings"
	"time"
)

// Shared gateways accept organization-managed endpoints. Pin DNS answers at dial
// time and reject private destinations unless the deployment explicitly trusts a host.
func ActveroSecureTransport(transport *http.Transport) {
	if os.Getenv("ACTVERO_ORGANIZATION_ISOLATION") != "true" {
		return
	}
	transport.Proxy = nil
	transport.DialContext = func(ctx context.Context, network, address string) (net.Conn, error) {
		host, port, err := net.SplitHostPort(address)
		if err != nil {
			return nil, err
		}
		allowed := false
		for _, entry := range strings.Split(os.Getenv("ACTVERO_EGRESS_PRIVATE_TARGETS"), ",") {
			if strings.EqualFold(strings.TrimSpace(entry), address) {
				allowed = true
			}
		}
		addresses, err := net.DefaultResolver.LookupIPAddr(ctx, host)
		if err != nil {
			return nil, err
		}
		if len(addresses) == 0 {
			return nil, errors.New("empty gateway DNS response")
		}
		for _, entry := range addresses {
			ip := entry.IP
			if !allowed && (!ip.IsGlobalUnicast() || ip.IsPrivate() || ip.IsLoopback() || ip.IsLinkLocalUnicast() || ip.IsLinkLocalMulticast() || strings.HasPrefix(ip.String(), "100.100.") || isActveroCarrierGrade(ip)) {
				return nil, errors.New("gateway destination is not permitted")
			}
		}
		dialer := net.Dialer{Timeout: 30 * time.Second, KeepAlive: 30 * time.Second}
		var last error
		for _, entry := range addresses {
			conn, e := dialer.DialContext(ctx, network, net.JoinHostPort(entry.IP.String(), port))
			if e == nil {
				return conn, nil
			}
			last = e
		}
		return nil, last
	}
}
func isActveroCarrierGrade(ip net.IP) bool {
	v := ip.To4()
	return v != nil && v[0] == 100 && v[1] >= 64 && v[1] <= 127
}
