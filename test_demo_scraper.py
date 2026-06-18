import unittest

from demo_scraper import extract_business_data, validate_public_url


class DemoScraperTests(unittest.TestCase):
    def test_validate_public_url_adds_https(self):
        self.assertEqual(
            validate_public_url("example.com"),
            "https://example.com",
        )

    def test_extract_business_data_parses_basic_fields(self):
        html = """
        <html>
          <head>
            <title>Sunrise Dental | Family Dentistry</title>
            <meta name="description" content="Friendly dental care in Ottawa.">
          </head>
          <body>
            <h1>Sunrise Dental</h1>
            <h2>Our Services</h2>
            <ul><li>Cleanings</li><li>Whitening</li></ul>
            <h2>Contact</h2>
            <p>Call us at (613) 555-0100 or email hello@sunrise.example</p>
            <h2>Hours</h2>
            <p>Mon-Fri 9am-5pm</p>
          </body>
        </html>
        """

        data = extract_business_data(html, "https://sunrise.example")

        self.assertEqual(data["name"], "Sunrise Dental")
        self.assertIn("Friendly dental care", data["description"])
        self.assertIn("Cleanings", data["services"])
        self.assertIn("613", data["contact"])
        self.assertIn("Mon-Fri", data["hours"])


if __name__ == "__main__":
    unittest.main()
