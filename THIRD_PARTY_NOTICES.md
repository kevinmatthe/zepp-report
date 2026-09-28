# Third-party notices

Zepp API endpoint structure, field mappings, sleep stage mapping and Base64 decoding are adapted from:

- https://github.com/EvanCooke/zepp-export
- Reference commit: 42e54db39074a92f289d83d28fef0cad9c468a3e

This project independently implements persistence, scheduling, authentication, a UI and VictoriaMetrics integration. It is not affiliated with Zepp Health. Upstream license follows.

MIT License

Copyright (c) 2026 zepp-export contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.


Additional API research references (independent implementation, no copied application code):

- Workout cursor/source handling: https://github.com/rolandsz/Mi-Fit-and-Zepp-workout-exporter/blob/04bc0e28bf9ed7b77ed7251187396f5df3d6e881/src/api.py
- Confirmed workout type codes: https://github.com/DhavalBhimani44/zepp-mcp/blob/9ba4f58ec19c300a74751386fc9a8d22aebbbfff/zepp_mcp/codes.py

Frontend uses Apache ECharts, zrender, Flatpickr and tslib. Exact versions are
locked in package-lock.json. Their licenses and notices are reproduced in the
bundled static/dist/THIRD_PARTY_LICENSES.txt generated during the image build.
