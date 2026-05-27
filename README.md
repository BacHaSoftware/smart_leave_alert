<a name="readme-top"></a>

<!-- PROJECT DETAILS -->
<br />
<div align="center">
  <a href="https://github.com/BacHaSoftware/smart_leave_alert">
    <img src="/bhs_hr_leave_alert/static/description/imgs/logo.png" alt="Logo" height="80">
  </a>

  <h3 align="center">Smart Leave Alert</h3>

  <p align="center">
    A product of Bac Ha Software that alerts users when their leave exceeds their annual leave allowance.
  </p>
</div>



<!-- TABLE OF CONTENTS -->
<details>
  <summary>Table of Contents</summary>
  <ol>
    <li><a href="#about-the-project">About The Project</a></li>
    <li>
      <a href="#getting-started">Getting Started</a>
      <ul>
        <li><a href="#installation">Installation</a></li>
      </ul>
    </li>
    <li><a href="#usage">Usage</a></li>
    <li><a href="#license">License</a></li>
    <li><a href="#contact-us">Contact us</a></li>
  </ol>
</details>



<!-- ABOUT THE PROJECT -->
## About The Project

<div align="left">
  <a href="https://github.com/BacHaSoftware/smart_leave_alert/">
    <img src="/bhs_hr_leave_alert/static/description/banner.jpg" alt="Smart Leave Alert">
  </a>
</div>

Smart Leave Alert extends Odoo Time Off to help employees and managers monitor annual leave usage when leave requests are submitted or updated.

#### Key Features:

* <code>Allocation Period Validation</code>: Prevent leave requests from consuming allocations that do not cover the requested dates.
* <code>Annual Leave Balance Check</code>: Prevent creation or updates of paid time off requests when the available allocation is insufficient.
* <code>Smart Warning Notification</code>: Send an Odoo notification when used annual leave exceeds the accrued monthly allowance for the year.

<p align="right">(<a href="#readme-top">back to top</a>)</p>


<!-- GETTING STARTED -->
## Getting Started

### Installation

Install module <code>bhs_hr_leave_alert</code>. The Odoo <code>hr_holidays</code> dependency is installed automatically when required.

<p align="right">(<a href="#readme-top">back to top</a>)</p>


<!-- USAGE EXAMPLES -->
## Usage

Create or modify an annual paid time off request. The module verifies that the employee has an allocation covering the requested dates and enough remaining allocated days.

When the request uses more annual leave than the accrued number of worked months in the current year, the request is preserved and a visible warning is sent to the user and recorded in the chatter.

#### Featured Highlight:

* <code>Instant Alerts</code>: Users receive warning notifications as soon as excessive annual leave usage is detected.
* <code>Controlled Consumption</code>: Leave cannot be taken against allocations outside the valid date range.

<p align="right">(<a href="#readme-top">back to top</a>)</p>


<!-- LICENSE -->
## License

Distributed under the MIT License. See `LICENSE.md` for more information.

<p align="right">(<a href="#readme-top">back to top</a>)</p>



<!-- CONTACT US-->
## Contact Us

Need assistance with setup or have any concerns? Contact Bac Ha Software directly for support:

<div align="left">
  <a href="https://github.com/BacHaSoftware">
    <img src="/bhs_hr_leave_alert/static/description/imgs/logo.png" alt="Logo" height="80">
  </a>
</div>

odoo@bachasoftware.com

[https://bachasoftware.com](https://bachasoftware.com)

[![WEBSITE][website-shield]][website-url] [![LinkedIn][linkedin-shield]][linkedin-url]

Project Link: [https://github.com/BacHaSoftware/smart_leave_alert/](https://github.com/BacHaSoftware/smart_leave_alert/)

<p align="right">(<a href="#readme-top">back to top</a>)</p>



<!-- MARKDOWN LINKS & IMAGES -->
[linkedin-shield]: https://img.shields.io/badge/-LinkedIn-black.svg?style=for-the-badge&logo=linkedin&colorB=555
[linkedin-url]: https://www.linkedin.com/company/bac-ha-software
[website-shield]: https://img.shields.io/badge/-website-black.svg?style=for-the-badge&logo=website&colorB=555
[website-url]: https://bachasoftware.com
